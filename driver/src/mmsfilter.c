/*
 * mmsfilter.sys — MagicMouse Studio filter driver (KMDF 1.15)
 *
 * Stage 1 (this file): USB.  Lower filter under HidUsb on USB\VID_05AC&PID_0269&MI_01.
 *   The USB HID descriptor of the Magic Mouse 2 declares no feature reports, so user mode
 *   (HidD_SetFeature) cannot switch the mouse into multi-touch mode.  This filter sends the
 *   HID class request SET_REPORT(Feature) directly on the default control pipe:
 *       bmRequestType 0x21, bRequest 0x09, wValue 0x03<id>, wIndex <interface>, data <report>
 *   Default report: F1 02 01 (what Apple's driver sends to MM2); configurable at runtime.
 *   All HID traffic passes through untouched; touch frames are read by the app from the
 *   vendor collection (MI_01&COL03) with standard HID APIs.
 *
 * Control device \\.\MagicMouseStudio (interactive users RW):
 *   IOCTL_MMS_SET_FEATURE  in: report bytes (report id first, 1..64) -> SET_REPORT(Feature) now
 *   IOCTL_MMS_GET_STATUS   out: MMS_STATUS
 *
 * Own code, written from the documented wire protocol; no third-party driver code.
 */
#include <ntddk.h>
#include <wdf.h>
#include <usb.h>
#include <wdfusb.h>
#include <usbioctl.h>
#include <bthdef.h>
#include <bthioctl.h>
#include <bthddi.h>
#include "mmsfilter_public.h"

#define RING_SIZE 64

#define MMS_TAG 'SMMM'
#define HID_SET_REPORT 0x09
#define HID_REPORT_TYPE_FEATURE 0x03

typedef struct _FILTER_CTX {
    WDFDEVICE      Device;
    WDFUSBDEVICE   UsbDevice;
    UCHAR          InterfaceNumber;
    BOOLEAN        IsUsb;            /* FALSE = Bluetooth (BTHENUM) */
    WDFTIMER       EnableTimer;
} FILTER_CTX, *PFILTER_CTX;
WDF_DECLARE_CONTEXT_TYPE_WITH_NAME(FILTER_CTX, FilterGetCtx)

DRIVER_INITIALIZE DriverEntry;
EVT_WDF_DRIVER_DEVICE_ADD MmsEvtDeviceAdd;
EVT_WDF_DEVICE_PREPARE_HARDWARE MmsEvtPrepareHardware;
EVT_WDF_DEVICE_D0_ENTRY MmsEvtD0Entry;
EVT_WDF_OBJECT_CONTEXT_CLEANUP MmsEvtFilterCleanup;
EVT_WDF_TIMER MmsEvtEnableTimer;
EVT_WDF_IO_QUEUE_IO_DEVICE_CONTROL MmsEvtControlIoctl;
EVT_WDF_IO_QUEUE_IO_INTERNAL_DEVICE_CONTROL MmsEvtInternalIoctl;
EVT_WDF_REQUEST_COMPLETION_ROUTINE MmsUrbComplete;
EVT_WDF_REQUEST_COMPLETION_ROUTINE MmsBrbComplete;

/* ---- raw frame ring + pended readers (spinlock: touched at DISPATCH_LEVEL) ---- */
static WDFSPINLOCK g_RingLock;
static WDFQUEUE    g_ReadQueue;      /* manual queue on the control device */
static MMS_FRAME   g_Ring[RING_SIZE];
static ULONG       g_RingHead, g_RingCount, g_Seq, g_DroppedSinceLast;

/* ---- globals (one mouse at a time is enough for this tool) ---- */
static WDFWAITLOCK g_Lock;
static WDFDEVICE   g_ControlDevice;
static WDFDEVICE   g_ActiveFilter;   /* last started filter device */
static LONG        g_FilterCount;
static MMS_STATUS  g_Status;
static UCHAR       g_EnableReport[MMS_MAX_REPORT] = { 0xF1, 0x02, 0x01 };
static ULONG       g_EnableLen = 3;

DECLARE_CONST_UNICODE_STRING(g_CtlName, L"\\Device\\MagicMouseStudio");
DECLARE_CONST_UNICODE_STRING(g_CtlLink, L"\\DosDevices\\MagicMouseStudio");
/* SYSTEM + Administrators: all; Interactive users: read/write */
DECLARE_CONST_UNICODE_STRING(g_CtlSddl, L"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)");

/* ------------------------------------------------------------------ */
static NTSTATUS SendSetFeature(PFILTER_CTX ctx, const UCHAR *report, ULONG len)
{
    WDF_USB_CONTROL_SETUP_PACKET pkt;
    WDF_MEMORY_DESCRIPTOR mem;
    WDF_REQUEST_SEND_OPTIONS opts;
    UCHAR buf[MMS_MAX_REPORT];
    ULONG sent = 0;
    NTSTATUS st;

    PAGED_CODE();
    if (ctx->UsbDevice == NULL || len == 0 || len > MMS_MAX_REPORT) {
        return STATUS_INVALID_DEVICE_STATE;
    }
    RtlCopyMemory(buf, report, len);
    WDF_USB_CONTROL_SETUP_PACKET_INIT_CLASS(&pkt, BmRequestHostToDevice, BmRequestToInterface,
                                            HID_SET_REPORT,
                                            (USHORT)((HID_REPORT_TYPE_FEATURE << 8) | report[0]),
                                            ctx->InterfaceNumber);
    WDF_MEMORY_DESCRIPTOR_INIT_BUFFER(&mem, buf, len);
    WDF_REQUEST_SEND_OPTIONS_INIT(&opts, WDF_REQUEST_SEND_OPTION_TIMEOUT);
    WDF_REQUEST_SEND_OPTIONS_SET_TIMEOUT(&opts, WDF_REL_TIMEOUT_IN_SEC(2));
    st = WdfUsbTargetDeviceSendControlTransferSynchronously(ctx->UsbDevice, WDF_NO_HANDLE, &opts, &pkt, &mem, &sent);

    g_Status.LastStatus = st;
    g_Status.LastBytes = sent;
    g_Status.SendCount++;
    g_Status.LastLen = len;
    RtlCopyMemory(g_Status.LastReport, buf, len);
    KdPrintEx((DPFLTR_IHVDRIVER_ID, DPFLTR_INFO_LEVEL, "mmsfilter: SET_REPORT id=%02X len=%u -> %08X (%u)\n",
               report[0], len, st, sent));
    return st;
}

/* ---- raw frames ------------------------------------------------- */
/* Copies one frame into a pended IOCTL_MMS_READ_FRAME request. Caller holds g_RingLock. */
static VOID CompleteRead(WDFREQUEST req, const MMS_FRAME *f)
{
    PMMS_FRAME out;
    NTSTATUS st = WdfRequestRetrieveOutputBuffer(req, sizeof(MMS_FRAME), (PVOID *)&out, NULL);
    if (NT_SUCCESS(st)) {
        RtlCopyMemory(out, f, sizeof(MMS_FRAME));
        WdfRequestCompleteWithInformation(req, STATUS_SUCCESS, sizeof(MMS_FRAME));
    } else {
        WdfRequestComplete(req, st);
    }
}

/* Called at <= DISPATCH_LEVEL for every raw input packet coming up from the mouse. */
static VOID PushFrame(ULONG source, const UCHAR *data, ULONG len)
{
    MMS_FRAME *f;
    WDFREQUEST req;

    if (len == 0) return;
    if (len > MMS_FRAME_MAX) len = MMS_FRAME_MAX;

    WdfSpinLockAcquire(g_RingLock);
    g_Status.FramesSeen++;
    /* the mouse sends its battery report (90 flags percent) only on connect / change: cache it */
    if (source == MMS_SOURCE_BT && len >= 3 && data[0] == 0x90 && data[2] <= 100) {
        g_Status.BatteryFlags = data[1];
        g_Status.BatteryPercent = data[2];
        g_Status.BatteryTime100ns = KeQueryInterruptTime();
    }
    if (g_RingCount == RING_SIZE) {          /* full: overwrite oldest */
        g_RingHead = (g_RingHead + 1) % RING_SIZE;
        g_RingCount--;
        g_Status.FramesDropped++;
        g_DroppedSinceLast++;
    }
    f = &g_Ring[(g_RingHead + g_RingCount) % RING_SIZE];
    f->Seq = ++g_Seq;
    f->Source = source;
    f->Length = len;
    f->Time100ns = KeQueryInterruptTime();
    RtlCopyMemory(f->Data, data, len);
    g_RingCount++;

    /* hand the oldest frame to a waiting reader, if any */
    if (g_ReadQueue && NT_SUCCESS(WdfIoQueueRetrieveNextRequest(g_ReadQueue, &req))) {
        MMS_FRAME *o = &g_Ring[g_RingHead];
        o->Dropped = g_DroppedSinceLast;
        g_DroppedSinceLast = 0;
        CompleteRead(req, o);
        g_RingHead = (g_RingHead + 1) % RING_SIZE;
        g_RingCount--;
    }
    WdfSpinLockRelease(g_RingLock);
}

/* USB: watch interrupt-IN transfers that HidUsb sends down; copy what the mouse returns. */
VOID MmsEvtInternalIoctl(WDFQUEUE Queue, WDFREQUEST Request, size_t OutLen, size_t InLen, ULONG Code)
{
    WDFDEVICE dev = WdfIoQueueGetDevice(Queue);
    WDFIOTARGET target = WdfDeviceGetIoTarget(dev);
    WDF_REQUEST_SEND_OPTIONS opts;
    UNREFERENCED_PARAMETER(OutLen);
    UNREFERENCED_PARAMETER(InLen);

    if (Code == IOCTL_INTERNAL_USB_SUBMIT_URB) {
        PURB urb = (PURB)IoGetCurrentIrpStackLocation(WdfRequestWdmGetIrp(Request))->Parameters.Others.Argument1;
        if (urb && urb->UrbHeader.Function == URB_FUNCTION_BULK_OR_INTERRUPT_TRANSFER &&
            (urb->UrbBulkOrInterruptTransfer.TransferFlags & USBD_TRANSFER_DIRECTION_IN)) {
            WdfRequestFormatRequestUsingCurrentType(Request);
            WdfRequestSetCompletionRoutine(Request, MmsUrbComplete, (WDFCONTEXT)urb);
            InterlockedIncrement((LONG *)&g_Status.UrbsHooked);
            if (WdfRequestSend(Request, target, WDF_NO_SEND_OPTIONS)) return;
            WdfRequestComplete(Request, WdfRequestGetStatus(Request));
            return;
        }
    } else if (Code == IOCTL_INTERNAL_BTH_SUBMIT_BRB) {
        /* Bluetooth: passive tap of incoming L2CAP data (interrupt + control channel).
           Nothing is modified; the driver above (Apple/HidBth) sees exactly the same bytes. */
        BRB_HEADER *hdr = (BRB_HEADER *)IoGetCurrentIrpStackLocation(WdfRequestWdmGetIrp(Request))->Parameters.Others.Argument1;
        if (hdr && hdr->Type == BRB_L2CA_ACL_TRANSFER &&
            (((struct _BRB_L2CA_ACL_TRANSFER *)hdr)->TransferFlags & ACL_TRANSFER_DIRECTION_IN)) {
            WdfRequestFormatRequestUsingCurrentType(Request);
            WdfRequestSetCompletionRoutine(Request, MmsBrbComplete, (WDFCONTEXT)hdr);
            InterlockedIncrement((LONG *)&g_Status.UrbsHooked);
            if (WdfRequestSend(Request, target, WDF_NO_SEND_OPTIONS)) return;
            WdfRequestComplete(Request, WdfRequestGetStatus(Request));
            return;
        }
    }
    WDF_REQUEST_SEND_OPTIONS_INIT(&opts, WDF_REQUEST_SEND_OPTION_SEND_AND_FORGET);
    if (!WdfRequestSend(Request, target, &opts)) {
        WdfRequestComplete(Request, WdfRequestGetStatus(Request));
    }
}

VOID MmsUrbComplete(WDFREQUEST Request, WDFIOTARGET Target, PWDF_REQUEST_COMPLETION_PARAMS Params, WDFCONTEXT Context)
{
    PURB urb = (PURB)Context;
    UNREFERENCED_PARAMETER(Target);

    if (NT_SUCCESS(Params->IoStatus.Status) && urb) {
        struct _URB_BULK_OR_INTERRUPT_TRANSFER *t = &urb->UrbBulkOrInterruptTransfer;
        PUCHAR p = NULL;
        if (t->TransferBufferMDL) {
            p = (PUCHAR)MmGetSystemAddressForMdlSafe(t->TransferBufferMDL, NormalPagePriority | MdlMappingNoExecute);
        } else {
            p = (PUCHAR)t->TransferBuffer;
        }
        if (p && t->TransferBufferLength) {
            PushFrame(MMS_SOURCE_USB, p, t->TransferBufferLength);
        }
    }
    WdfRequestComplete(Request, Params->IoStatus.Status);
}

VOID MmsBrbComplete(WDFREQUEST Request, WDFIOTARGET Target, PWDF_REQUEST_COMPLETION_PARAMS Params, WDFCONTEXT Context)
{
    struct _BRB_L2CA_ACL_TRANSFER *acl = (struct _BRB_L2CA_ACL_TRANSFER *)Context;
    UNREFERENCED_PARAMETER(Target);

    if (NT_SUCCESS(Params->IoStatus.Status) && acl && acl->BufferSize) {
        PUCHAR p = acl->BufferMDL
            ? (PUCHAR)MmGetSystemAddressForMdlSafe(acl->BufferMDL, NormalPagePriority | MdlMappingNoExecute)
            : (PUCHAR)acl->Buffer;
        if (p) {
            if (p[0] == 0xA1 && acl->BufferSize > 1) {
                PushFrame(MMS_SOURCE_BT, p + 1, acl->BufferSize - 1);
            } else {
                PushFrame(MMS_SOURCE_BT_RAW, p, acl->BufferSize);
            }
        }
    }
    WdfRequestComplete(Request, Params->IoStatus.Status);
}

/* ------------------------------------------------------------------ */
NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    WDF_DRIVER_CONFIG cfg;
    WDFDRIVER driver;
    NTSTATUS st;

    WDF_DRIVER_CONFIG_INIT(&cfg, MmsEvtDeviceAdd);
    cfg.DriverPoolTag = MMS_TAG;
    st = WdfDriverCreate(DriverObject, RegistryPath, WDF_NO_OBJECT_ATTRIBUTES, &cfg, &driver);
    if (!NT_SUCCESS(st)) return st;

    st = WdfWaitLockCreate(WDF_NO_OBJECT_ATTRIBUTES, &g_Lock);
    if (!NT_SUCCESS(st)) return st;
    st = WdfSpinLockCreate(WDF_NO_OBJECT_ATTRIBUTES, &g_RingLock);
    if (!NT_SUCCESS(st)) return st;

    /* optional override: HKLM\...\Services\mmsfilter\Parameters\MtEnable (REG_BINARY) */
    {
        WDFKEY key;
        if (NT_SUCCESS(WdfDriverOpenParametersRegistryKey(driver, KEY_READ, WDF_NO_OBJECT_ATTRIBUTES, &key))) {
            DECLARE_CONST_UNICODE_STRING(name, L"MtEnable");
            UCHAR tmp[MMS_MAX_REPORT];
            ULONG got = 0, type = 0;
            if (NT_SUCCESS(WdfRegistryQueryValue(key, &name, sizeof(tmp), tmp, &got, &type)) &&
                type == REG_BINARY && got > 0 && got <= MMS_MAX_REPORT) {
                RtlCopyMemory(g_EnableReport, tmp, got);
                g_EnableLen = got;
            }
            WdfRegistryClose(key);
        }
    }
    g_Status.Version = MMS_VERSION;
    g_Status.BatteryPercent = -1;
    return STATUS_SUCCESS;
}

/* ---- control device -------------------------------------------- */
static NTSTATUS CreateControlDevice(WDFDRIVER driver)
{
    PWDFDEVICE_INIT init;
    WDF_IO_QUEUE_CONFIG qcfg;
    WDF_OBJECT_ATTRIBUTES attr;
    WDFQUEUE q;
    WDFDEVICE dev;
    NTSTATUS st;

    init = WdfControlDeviceInitAllocate(driver, &g_CtlSddl);
    if (init == NULL) return STATUS_INSUFFICIENT_RESOURCES;
    WdfDeviceInitSetExclusive(init, FALSE);
    st = WdfDeviceInitAssignName(init, &g_CtlName);
    if (!NT_SUCCESS(st)) { WdfDeviceInitFree(init); return st; }

    WDF_OBJECT_ATTRIBUTES_INIT(&attr);
    attr.ExecutionLevel = WdfExecutionLevelPassive;
    st = WdfDeviceCreate(&init, &attr, &dev);
    if (!NT_SUCCESS(st)) { if (init) WdfDeviceInitFree(init); return st; }

    st = WdfDeviceCreateSymbolicLink(dev, &g_CtlLink);
    if (!NT_SUCCESS(st)) { WdfObjectDelete(dev); return st; }

    WDF_IO_QUEUE_CONFIG_INIT_DEFAULT_QUEUE(&qcfg, WdfIoQueueDispatchSequential);
    qcfg.EvtIoDeviceControl = MmsEvtControlIoctl;
    st = WdfIoQueueCreate(dev, &qcfg, WDF_NO_OBJECT_ATTRIBUTES, &q);
    if (!NT_SUCCESS(st)) { WdfObjectDelete(dev); return st; }

    /* manual queue that parks IOCTL_MMS_READ_FRAME until a frame arrives */
    WDF_IO_QUEUE_CONFIG_INIT(&qcfg, WdfIoQueueDispatchManual);
    st = WdfIoQueueCreate(dev, &qcfg, WDF_NO_OBJECT_ATTRIBUTES, &q);
    if (!NT_SUCCESS(st)) { WdfObjectDelete(dev); return st; }
    WdfSpinLockAcquire(g_RingLock);
    g_ReadQueue = q;
    WdfSpinLockRelease(g_RingLock);

    WdfControlFinishInitializing(dev);
    g_ControlDevice = dev;
    return STATUS_SUCCESS;
}

VOID MmsEvtControlIoctl(WDFQUEUE Queue, WDFREQUEST Request, size_t OutLen, size_t InLen, ULONG Code)
{
    NTSTATUS st = STATUS_INVALID_DEVICE_REQUEST;
    size_t info = 0;
    UNREFERENCED_PARAMETER(Queue);
    UNREFERENCED_PARAMETER(OutLen);

    switch (Code) {
    case IOCTL_MMS_SET_FEATURE: {
        PUCHAR in;
        if (InLen == 0 || InLen > MMS_MAX_REPORT) { st = STATUS_INVALID_BUFFER_SIZE; break; }
        st = WdfRequestRetrieveInputBuffer(Request, InLen, (PVOID *)&in, NULL);
        if (!NT_SUCCESS(st)) break;
        WdfWaitLockAcquire(g_Lock, NULL);
        if (g_ActiveFilter) {
            st = SendSetFeature(FilterGetCtx(g_ActiveFilter), in, (ULONG)InLen);
            /* remember it: re-sent automatically on reconnect / power-up */
            if (NT_SUCCESS(st)) { RtlCopyMemory(g_EnableReport, in, InLen); g_EnableLen = (ULONG)InLen; }
        } else {
            st = STATUS_DEVICE_NOT_CONNECTED;
        }
        WdfWaitLockRelease(g_Lock);
        break;
    }
    case IOCTL_MMS_READ_FRAME: {
        if (OutLen < sizeof(MMS_FRAME)) { st = STATUS_BUFFER_TOO_SMALL; break; }
        WdfSpinLockAcquire(g_RingLock);
        if (g_RingCount) {
            MMS_FRAME *o = &g_Ring[g_RingHead];
            o->Dropped = g_DroppedSinceLast;
            g_DroppedSinceLast = 0;
            CompleteRead(Request, o);
            g_RingHead = (g_RingHead + 1) % RING_SIZE;
            g_RingCount--;
            WdfSpinLockRelease(g_RingLock);
            return;
        }
        st = g_ReadQueue ? WdfRequestForwardToIoQueue(Request, g_ReadQueue) : STATUS_DEVICE_NOT_READY;
        WdfSpinLockRelease(g_RingLock);
        if (NT_SUCCESS(st)) return;   /* pended */
        break;
    }
    case IOCTL_MMS_GET_STATUS: {
        PMMS_STATUS out;
        st = WdfRequestRetrieveOutputBuffer(Request, sizeof(MMS_STATUS), (PVOID *)&out, NULL);
        if (!NT_SUCCESS(st)) break;
        WdfWaitLockAcquire(g_Lock, NULL);
        g_Status.DeviceCount = (ULONG)g_FilterCount;
        g_Status.Connected = (g_ActiveFilter != NULL);
        WdfSpinLockAcquire(g_RingLock);
        g_Status.Now100ns = KeQueryInterruptTime();
        *out = g_Status;
        WdfSpinLockRelease(g_RingLock);
        WdfWaitLockRelease(g_Lock);
        info = sizeof(MMS_STATUS);
        break;
    }
    default:
        break;
    }
    WdfRequestCompleteWithInformation(Request, st, info);
}

/* ---- filter device ---------------------------------------------- */
NTSTATUS MmsEvtDeviceAdd(WDFDRIVER Driver, PWDFDEVICE_INIT DeviceInit)
{
    WDF_PNPPOWER_EVENT_CALLBACKS pnp;
    WDF_OBJECT_ATTRIBUTES attr;
    WDF_TIMER_CONFIG tcfg;
    WDFDEVICE dev;
    PFILTER_CTX ctx;
    NTSTATUS st;

    PAGED_CODE();
    WdfFdoInitSetFilter(DeviceInit);

    WDF_PNPPOWER_EVENT_CALLBACKS_INIT(&pnp);
    pnp.EvtDevicePrepareHardware = MmsEvtPrepareHardware;
    pnp.EvtDeviceD0Entry = MmsEvtD0Entry;
    WdfDeviceInitSetPnpPowerEventCallbacks(DeviceInit, &pnp);

    WDF_OBJECT_ATTRIBUTES_INIT_CONTEXT_TYPE(&attr, FILTER_CTX);
    attr.EvtCleanupCallback = MmsEvtFilterCleanup;
    st = WdfDeviceCreate(&DeviceInit, &attr, &dev);
    if (!NT_SUCCESS(st)) return st;

    ctx = FilterGetCtx(dev);
    ctx->Device = dev;

    /* default queue: only internal IOCTLs are inspected; every other request type is
       passed down automatically by KMDF because this is a filter device */
    {
        WDF_IO_QUEUE_CONFIG qcfg;
        WDFQUEUE q;
        WDF_IO_QUEUE_CONFIG_INIT_DEFAULT_QUEUE(&qcfg, WdfIoQueueDispatchParallel);
        qcfg.EvtIoInternalDeviceControl = MmsEvtInternalIoctl;
        qcfg.PowerManaged = WdfFalse;
        st = WdfIoQueueCreate(dev, &qcfg, WDF_NO_OBJECT_ATTRIBUTES, &q);
        if (!NT_SUCCESS(st)) return st;
    }

    WDF_TIMER_CONFIG_INIT(&tcfg, MmsEvtEnableTimer);
    tcfg.AutomaticSerialization = FALSE;   /* required for passive-level timers */
    WDF_OBJECT_ATTRIBUTES_INIT(&attr);
    attr.ParentObject = dev;
    attr.ExecutionLevel = WdfExecutionLevelPassive;
    st = WdfTimerCreate(&tcfg, &attr, &ctx->EnableTimer);
    if (!NT_SUCCESS(st)) return st;

    WdfWaitLockAcquire(g_Lock, NULL);
    if (InterlockedIncrement(&g_FilterCount) == 1 && g_ControlDevice == NULL) {
        NTSTATUS cst = CreateControlDevice(Driver);
        g_Status.ControlDeviceStatus = cst;   /* filter keeps working even if this fails */
    }
    WdfWaitLockRelease(g_Lock);
    return STATUS_SUCCESS;
}

NTSTATUS MmsEvtPrepareHardware(WDFDEVICE Device, WDFCMRESLIST Raw, WDFCMRESLIST Translated)
{
    PFILTER_CTX ctx = FilterGetCtx(Device);
    NTSTATUS st;
    UNREFERENCED_PARAMETER(Raw);
    UNREFERENCED_PARAMETER(Translated);

    PAGED_CODE();
    {
        WCHAR en[16] = { 0 };
        ULONG got = 0;
        DECLARE_CONST_UNICODE_STRING(usb, L"USB");
        UNICODE_STRING s;
        if (NT_SUCCESS(WdfDeviceQueryProperty(Device, DevicePropertyEnumeratorName, sizeof(en) - sizeof(WCHAR), en, &got))) {
            RtlInitUnicodeString(&s, en);
            ctx->IsUsb = RtlEqualUnicodeString(&s, &usb, TRUE);
        }
    }
    if (!ctx->IsUsb) {
        return STATUS_SUCCESS;          /* Bluetooth: passive tap only, no USB target */
    }
    if (ctx->UsbDevice == NULL) {
        /* control transfers only: the classic create (no USBD client contract) is enough */
        st = WdfUsbTargetDeviceCreate(Device, WDF_NO_OBJECT_ATTRIBUTES, &ctx->UsbDevice);
        g_Status.UsbCreateStatus = st;
        if (!NT_SUCCESS(st)) {
            ctx->UsbDevice = NULL;
            return STATUS_SUCCESS;  /* never break the mouse: just pass traffic through */
        }
        ctx->InterfaceNumber = 1;
        if (WdfUsbTargetDeviceGetNumInterfaces(ctx->UsbDevice) > 0) {
            WDFUSBINTERFACE itf = WdfUsbTargetDeviceGetInterface(ctx->UsbDevice, 0);
            if (itf) ctx->InterfaceNumber = WdfUsbInterfaceGetInterfaceNumber(itf);
        }
        g_Status.InterfaceNumber = ctx->InterfaceNumber;
    }
    return STATUS_SUCCESS;
}

NTSTATUS MmsEvtD0Entry(WDFDEVICE Device, WDF_POWER_DEVICE_STATE Previous)
{
    PFILTER_CTX ctx = FilterGetCtx(Device);
    UNREFERENCED_PARAMETER(Previous);

    WdfWaitLockAcquire(g_Lock, NULL);
    g_ActiveFilter = Device;
    WdfWaitLockRelease(g_Lock);
    /* USB only: let HidUsb finish starting, then send the enable report.
       (Bluetooth: the function-side driver above us does the enabling.) */
    if (ctx->IsUsb) {
        WdfTimerStart(ctx->EnableTimer, WDF_REL_TIMEOUT_IN_MS(700));
    }
    return STATUS_SUCCESS;
}

VOID MmsEvtEnableTimer(WDFTIMER Timer)
{
    WDFDEVICE dev = (WDFDEVICE)WdfTimerGetParentObject(Timer);
    WdfWaitLockAcquire(g_Lock, NULL);
    (VOID)SendSetFeature(FilterGetCtx(dev), g_EnableReport, g_EnableLen);
    WdfWaitLockRelease(g_Lock);
}

VOID MmsEvtFilterCleanup(WDFOBJECT Object)
{
    WDFDEVICE ctl = NULL;
    WdfWaitLockAcquire(g_Lock, NULL);
    if (g_ActiveFilter == (WDFDEVICE)Object) g_ActiveFilter = NULL;
    if (InterlockedDecrement(&g_FilterCount) == 0 && g_ControlDevice) {
        ctl = g_ControlDevice;
        g_ControlDevice = NULL;
        WdfSpinLockAcquire(g_RingLock);
        g_ReadQueue = NULL;     /* the queue dies with the control device */
        WdfSpinLockRelease(g_RingLock);
    }
    WdfWaitLockRelease(g_Lock);
    if (ctl) {
        WdfObjectDelete(ctl);   /* outside the lock (its queue may be finishing an IOCTL); lets the driver unload */
    }
}
