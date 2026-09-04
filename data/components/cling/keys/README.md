# Keys

Cling puts nothing here. This folder is for a key you supply, for a package
Cling cannot otherwise open.

**Klango's `.pag` packages need nothing.** Cling reads them: the concealment was
recovered from `klangoplayer.exe` and is

    plain[i] = cipher[i] ^ ((i + 0xFC) & 0xFF) ^ 0xC6

with a zlib-compressed directory of `(name, md5, offset, size, compressed)`
records under it. Every file carries the MD5 of its own uncompressed content, so
Cling checks each one as it extracts it rather than hoping.

## `*.txt` - keys for `.kpak` packages

`.kpak` is the container the German Klango reimplementation uses, and that one
IS encrypted with a key held by the client that made it. One key per line,
hexadecimal or base64, 16, 24 or 32 bytes. Lines starting with `#` are ignored.
