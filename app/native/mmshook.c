/*
 * mmshook.dll — native WH_MOUSE_LL hook for MagicMouse Studio.
 *
 * Why native: a Python low-level hook is called for EVERY mouse move of EVERY mouse and has to take
 * the GIL; when Python is busy the cursor stutters and Windows silently removes slow hooks.
 * Here mouse moves pass with zero work, and decisions about wheel/click events use plain shared
 * state that the Python engine updates from the touch frames:
 *   mms_touch()        - a finger is on the Apple mouse right now          (every touch frame)
 *   mms_set_click(map) - the Apple mouse was just physically clicked; map = buttons to emit
 *                        (bit0 left, bit1 right, bit2 middle; 0 = swallow the click)
 *   mms_config(...)    - who owns scroll / clicks, global enable
 * Wheel events are swallowed only while the Apple mouse is being touched; a physical left/right
 * press is re-mapped only if a matching Apple click arrives within the wait window — any other mouse
 * passes untouched.
 */
#include <windows.h>

#define MMS_TAG 0x4D4D5354ULL
#define EXPORT __declspec(dllexport)

typedef struct {
    LONG wheel_seen, wheel_swallowed, click_apple, click_other, alive, hook_error;
} MMS_STATS;

static volatile LONG64 g_last_touch;          /* QPC ticks */
static volatile LONG64 g_click_qpc;
static volatile LONG   g_click_map;
static volatile LONG   g_scroll_studio = 1, g_click_studio = 1, g_enabled = 1;
static LONG   g_touch_window_ms = 150, g_click_wait_ms = 60, g_click_age_ms = 150;
static LONG   g_mapped[2] = { -1, -1 };      /* physical left/right -> emitted map */
static LARGE_INTEGER g_freq;
static HANDLE g_click_event, g_thread, g_ready;
static DWORD  g_tid;
static HHOOK  g_hook;
static HMODULE g_self;
static MMS_STATS g_stats;

static LONG64 now_qpc(void) { LARGE_INTEGER t; QueryPerformanceCounter(&t); return t.QuadPart; }
static LONG64 ms_to_qpc(LONG ms) { return g_freq.QuadPart * ms / 1000; }

/* ---- injection worker -------------------------------------------------------------
 * NEVER call SendInput inside the hook procedure: Windows runs injected input through the
 * low-level hooks synchronously, so SendInput would wait for this very hook thread -> deadlock,
 * a dead system-wide hook (stuttering cursor, every SendInput on the machine hangs).
 * The hook only queues; this thread injects after the hook has returned. */
#define QSIZE 64
static volatile LONG g_q_head, g_q_tail;
static LONG g_q_map[QSIZE];
static BOOL g_q_down[QSIZE];
static CRITICAL_SECTION g_q_lock;
static HANDLE g_q_event, g_inj_thread;
static volatile LONG g_inj_stop;
static volatile LONG64 g_inj_busy;          /* QPC when SendInput started, 0 = idle */

static void emit(LONG map, BOOL down);

static void queue_emit(LONG map, BOOL down)
{
    EnterCriticalSection(&g_q_lock);
    if (g_q_tail - g_q_head < QSIZE) {
        g_q_map[g_q_tail % QSIZE] = map;
        g_q_down[g_q_tail % QSIZE] = down;
        g_q_tail++;
    }
    LeaveCriticalSection(&g_q_lock);
    SetEvent(g_q_event);
}

static DWORD WINAPI inject_thread(LPVOID arg)
{
    UNREFERENCED_PARAMETER(arg);
    while (!g_inj_stop) {
        WaitForSingleObject(g_q_event, 200);
        for (;;) {
            LONG map = 0; BOOL down = FALSE; BOOL have = FALSE;
            EnterCriticalSection(&g_q_lock);
            if (g_q_head != g_q_tail) {
                map = g_q_map[g_q_head % QSIZE];
                down = g_q_down[g_q_head % QSIZE];
                g_q_head++;
                have = TRUE;
            }
            LeaveCriticalSection(&g_q_lock);
            if (!have) break;
            emit(map, down);
        }
    }
    return 0;
}

static void emit(LONG map, BOOL down)
{
    INPUT in[3];
    UINT n = 0;
    static const DWORD dn[3] = { MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_MIDDLEDOWN };
    static const DWORD up[3] = { MOUSEEVENTF_LEFTUP, MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_MIDDLEUP };
    ZeroMemory(in, sizeof(in));
    for (int i = 0; i < 3; i++) {
        int b = down ? i : 2 - i;
        if (map & (1 << b)) {
            in[n].type = INPUT_MOUSE;
            in[n].mi.dwFlags = down ? dn[b] : up[b];
            in[n].mi.dwExtraInfo = (ULONG_PTR)MMS_TAG;
            n++;
        }
    }
    if (n) {
        InterlockedExchange64(&g_inj_busy, now_qpc());
        SendInput(n, in, sizeof(INPUT));
        InterlockedExchange64(&g_inj_busy, 0);
    }
}

static LRESULT CALLBACK hook_proc(int code, WPARAM wp, LPARAM lp)
{
    if (code == HC_ACTION && wp != WM_MOUSEMOVE && g_enabled &&
        !(g_inj_busy && now_qpc() - g_inj_busy > ms_to_qpc(300))) {   /* injection stuck: pass everything */
        const MSLLHOOKSTRUCT *m = (const MSLLHOOKSTRUCT *)lp;
        if (!(m->flags & LLMHF_INJECTED) && m->dwExtraInfo != (ULONG_PTR)MMS_TAG) {
            switch (wp) {
            case WM_MOUSEWHEEL:
            case WM_MOUSEHWHEEL:
                InterlockedIncrement(&g_stats.wheel_seen);
                if (g_scroll_studio && now_qpc() - g_last_touch < ms_to_qpc(g_touch_window_ms)) {
                    InterlockedIncrement(&g_stats.wheel_swallowed);
                    return 1;
                }
                break;
            case WM_LBUTTONDOWN:
            case WM_RBUTTONDOWN: {
                int phys = (wp == WM_RBUTTONDOWN);
                LONG64 deadline;
                if (!g_click_studio) break;
                /* nobody touches the Apple mouse -> it cannot be its click: never delay other mice */
                if (now_qpc() - g_last_touch > ms_to_qpc(500) && !g_click_qpc) {
                    InterlockedIncrement(&g_stats.click_other);
                    break;
                }
                deadline = now_qpc() + ms_to_qpc(g_click_wait_ms);
                for (;;) {
                    LONG64 t = now_qpc();
                    LONG64 c = g_click_qpc;
                    if (c && t - c < ms_to_qpc(g_click_age_ms)) {
                        LONG map = g_click_map;
                        InterlockedExchange64(&g_click_qpc, 0);     /* consume */
                        g_mapped[phys] = map;
                        InterlockedIncrement(&g_stats.click_apple);
                        queue_emit(map, TRUE);       /* injected later, outside the hook */
                        return 1;
                    }
                    if (t >= deadline) break;
                    WaitForSingleObject(g_click_event, (DWORD)(((deadline - t) * 1000) / g_freq.QuadPart) + 1);
                }
                InterlockedIncrement(&g_stats.click_other);
                break;
            }
            case WM_LBUTTONUP:
            case WM_RBUTTONUP: {
                int phys = (wp == WM_RBUTTONUP);
                LONG map = g_mapped[phys];
                if (map >= 0) {
                    g_mapped[phys] = -1;
                    queue_emit(map, FALSE);
                    return 1;
                }
                break;
            }
            }
        }
    }
    return CallNextHookEx(NULL, code, wp, lp);
}

static DWORD WINAPI hook_thread(LPVOID arg)
{
    MSG msg;
    UNREFERENCED_PARAMETER(arg);
    /* the hook thread must never be starved: input waits for it */
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);
    g_hook = SetWindowsHookExW(WH_MOUSE_LL, hook_proc, g_self, 0);
    g_stats.hook_error = g_hook ? 0 : (LONG)GetLastError();
    g_stats.alive = g_hook != NULL;
    SetEvent(g_ready);
    if (!g_hook) return 1;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { }
    UnhookWindowsHookEx(g_hook);
    g_hook = NULL;
    g_stats.alive = 0;
    return 0;
}

EXPORT int mms_start(void)
{
    if (g_thread) return g_stats.alive;
    QueryPerformanceFrequency(&g_freq);
    InitializeCriticalSection(&g_q_lock);
    g_q_event = CreateEventW(NULL, FALSE, FALSE, NULL);
    g_inj_stop = 0;
    g_inj_thread = CreateThread(NULL, 0, inject_thread, NULL, 0, NULL);
    g_click_event = CreateEventW(NULL, FALSE, FALSE, NULL);
    g_ready = CreateEventW(NULL, TRUE, FALSE, NULL);
    g_thread = CreateThread(NULL, 0, hook_thread, NULL, 0, &g_tid);
    if (!g_thread) return 0;
    WaitForSingleObject(g_ready, 3000);
    return g_stats.alive;
}

EXPORT void mms_stop(void)
{
    if (!g_thread) return;
    PostThreadMessageW(g_tid, WM_QUIT, 0, 0);
    WaitForSingleObject(g_thread, 2000);
    CloseHandle(g_thread);
    g_thread = NULL;
    if (g_inj_thread) {
        g_inj_stop = 1;
        SetEvent(g_q_event);
        WaitForSingleObject(g_inj_thread, 1000);   /* if SendInput is stuck system-wide, don't wait forever */
        CloseHandle(g_inj_thread);
        g_inj_thread = NULL;
    }
}

EXPORT void mms_touch(void) { InterlockedExchange64(&g_last_touch, now_qpc()); }

EXPORT void mms_set_click(int map)
{
    g_click_map = map;
    InterlockedExchange64(&g_click_qpc, now_qpc());
    SetEvent(g_click_event);
}

EXPORT void mms_config(int scroll_studio, int click_studio, int enabled)
{
    g_scroll_studio = scroll_studio;
    g_click_studio = click_studio;
    g_enabled = enabled;
}

EXPORT void mms_stats(MMS_STATS *out) { if (out) *out = g_stats; }

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r)
{
    UNREFERENCED_PARAMETER(r);
    if (reason == DLL_PROCESS_ATTACH) { g_self = h; DisableThreadLibraryCalls(h); }
    return TRUE;
}
