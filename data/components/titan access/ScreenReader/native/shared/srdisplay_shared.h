/*
 * srdisplay_shared.h - layout of the per-process GDI display-model section.
 *
 * Shared between the injected srremote.dll (writer, runs inside every target
 * process) and ScreenReaderHelper.dll (reader, runs in the screen reader
 * process). Keep both build units in sync with this header.
 *
 * Design: srremote.dll IAT-hooks ExtTextOutW inside each process it is loaded
 * into and appends a text-draw record to a fixed-size ring buffer in a named
 * shared-memory section. ScreenReaderHelper.dll opens that section by PID and
 * reads back the text for a given window. No per-draw cross-process IPC: the
 * writer only touches local shared memory, so a busy app is never blocked on
 * the screen reader process.
 */
#ifndef SRDISPLAY_SHARED_H
#define SRDISPLAY_SHARED_H

#include <stdint.h>

/* WCHARs per record, including the null terminator. Longer runs are truncated. */
#define SRD_MAX_TEXT       128

/* Number of records in the ring buffer. Oldest records are overwritten. */
#define SRD_RING_CAPACITY  4096

#define SRD_MAGIC    0x53524431u  /* 'SRD1' */
#define SRD_VERSION  1u

/* Name templates (printf-style, fed the target PID). ANSI names; same session. */
#define SRD_SECTION_FMT  "ScreenReaderDisplayModel_%lu"
#define SRD_MUTEX_FMT    "ScreenReaderDisplayModelMutex_%lu"

/* Section holding the screen reader's own PID, so srremote can skip the host. */
#define SRD_HOSTPID_SECTION  "ScreenReaderHelperHostPid"

#pragma pack(push, 8)

/* One recorded ExtTextOutW call. */
struct SrdRecord {
    uint64_t hwnd;                  /* owning window (WindowFromDC), 0 if unknown */
    int32_t  left, top, right, bottom;
    uint32_t seq;                   /* monotonic write sequence (newer = larger) */
    uint16_t text[SRD_MAX_TEXT];    /* UTF-16, null-terminated, truncated */
};

/* The whole shared section. */
struct SrdSharedHeader {
    uint32_t  magic;                /* SRD_MAGIC once initialised */
    uint32_t  version;              /* SRD_VERSION */
    uint32_t  writeIndex;           /* next ring slot to write (mod capacity) */
    uint32_t  totalWrites;          /* total records ever written */
    SrdRecord records[SRD_RING_CAPACITY];
};

#pragma pack(pop)

#endif /* SRDISPLAY_SHARED_H */
