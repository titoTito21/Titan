This build of BRLTTY 6.9.1 includes Windows-specific patches.

You should probably read doc/BRLTTY.txt and doc/Windows.txt for information
about BRLTTY.

Here are some notes on how to get started:

- BRLTTY only gives access to text consoles. For the rest of the Windows
  environment, you need to also install and run NVDA.
- Either use the BRLTTY configurator (brlttycnf.exe) or manually uncomment the
  appropriate lines in etc/brltty.conf.
- For Python support (e.g. for NVDA), install Brlapi-0.8.8-<PythonVersion>-win32.whl using pip.
- For sighted users, use the xw braille driver to get a virtual braille box.

- To register BRLTTY as a service so that it will get started automatically at
  boot, run enable-brlapi.bat. To unregister it, run disable-brlapi.bat.
- If your braille device uses a USB connection:
  * If you either cannot, or would prefer not to, install its
    manufacturer's driver, then you can select "USB:", and install
    the LibUSB-1.0 (aka LibUSBx) driver by doing one of the following:
    + right-clicking on bin/brltty-libusb-1.0.inf and selecting install
    + answering yes to the setup prompt for installing the LibUSB-1.0 (aka LibUSBx) driver
  * If you have installed its manufacturer's driver, and if that driver defines
    a virtual COM port, then select that virtual COM port.
  * If you need to install its manufacturer's driver, but
    that driver does not define a virtual COM port, then 
    you will need to use LibUSB (aka LibUSB-Win32) instead because
    LibUSB-1.0 (aka LibUSBx) does not support this requirement.
- If your braille device uses a serial connection, or if it is connected via a
  serial to USB converter, then select the correct COM port. Make sure to
  select the correct braille driver as well, because serial autodetection may
  brick some devices.
- If your braille device uses a Bluetooth connection, you can either use the
  Windows Bluetooth facilities to create a virtual COM port which you can then
  select, or manually configure the braille-device line in brltty.conf.

If you are having problems, please run debug-brltty.bat and send us the
debug.log and brltty.conf files.

Documentation can be found in the doc/ subdirectory.

==============================
Technical notes on this build:

- Source Revision: BRLTTY-6.9.1
- BRLTTY Version: 6.9.1
- BrlAPI Version: 0.8.8
- Some MinGW-specific path and file name changes have been made.
- To make life easier for Windows users, the BrlAPI server was modified to:
  * not use authentication by default (BRLAPI_DEFAUTH set to none)
  * only use local sockets (:0+127.0.0.1:0 changed to :0)
- *usb-1.0* files come from LibUSB-1.0 (aka LibUSBx) 1.0.18, which can be found at:
  http://www.libusb.org/wiki/windows_backend
- Python bindings are provided by: Brlapi-0.8.8-<PythonVersion>-win32.whl
- C bindings are provided in: include/, and lib/
  A .lib file is provided for linking in (for example) Visual C. Then you can
  just ship bin/brlapi0.8.dll alongside your .exe application.

