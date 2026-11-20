/* Shared between mmsfilter.sys and user mode (the Python app mirrors these values). */
#pragma once

#define MMS_VERSION     0x00010100u
#define MMS_MAX_REPORT  64

#define FILE_DEVICE_MMS 0x8A4D   /* vendor range */
#define IOCTL_MMS_SET_FEATURE CTL_CODE(FILE_DEVICE_MMS, 0x801, METHOD_BUFFERED, FILE_WRITE_ACCESS)
#define IOCTL_MMS_GET_STATUS  CTL_CODE(FILE_DEVICE_MMS, 0x802, METHOD_BUFFERED, FILE_READ_ACCESS)
/* out: MMS_FRAME. Pends until the next raw input packet from the mouse (inverted call). */
#define IOCTL_MMS_READ_FRAME  CTL_CODE(FILE_DEVICE_MMS, 0x803, METHOD_BUFFERED, FILE_READ_ACCESS)

#define MMS_FRAME_MAX     512
#define MMS_SOURCE_USB    1
#define MMS_SOURCE_BT     2   /* BT interrupt/control data, HIDP 0xA1 (DATA|Input) header stripped */
#define MMS_SOURCE_BT_RAW 3   /* BT packet with any other HIDP header (kept as-is, e.g. A3 = Feature data) */

typedef struct _MMS_FRAME {
    unsigned long       Seq;
    unsigned long       Source;       /* MMS_SOURCE_* */
    unsigned long       Length;       /* valid bytes in Data (report id first; BT: without the A1 header) */
    unsigned long       Dropped;      /* frames lost since the previous delivered frame */
    unsigned long long  Time100ns;    /* KeQueryInterruptTime() */
    unsigned char       Data[MMS_FRAME_MAX];
} MMS_FRAME, *PMMS_FRAME;

typedef struct _MMS_STATUS {
    unsigned long  Version;
    unsigned long  DeviceCount;
    unsigned long  Connected;
    long           ControlDeviceStatus;
    long           UsbCreateStatus;
    unsigned long  InterfaceNumber;
    unsigned long  SendCount;
    long           LastStatus;      /* NTSTATUS of last SET_REPORT */
    unsigned long  LastBytes;
    unsigned long  LastLen;
    unsigned char  LastReport[MMS_MAX_REPORT];
    unsigned long  FramesSeen;
    unsigned long  FramesDropped;
    unsigned long  UrbsHooked;
    long           BatteryPercent;    /* last 0x90 report seen (BT), -1 = none yet */
    unsigned long  BatteryFlags;
    unsigned long long BatteryTime100ns;  /* KeQueryInterruptTime() when it arrived */
    unsigned long long Now100ns;          /* KeQueryInterruptTime() when status was read */
} MMS_STATUS, *PMMS_STATUS;
