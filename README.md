JTAG programming with FT232
==

This is a utility for programming an ATMEGA162 through its JTAG
interface, connected to a FT232 USB-to-serial adapter. The JTAG routines can be
used for other purposes (eg. debugging) and even other devices. [More details
on the blog post](https://ignamv.wordpress.com/?p=302).

Instructions
--

* Power the ATMEGA162 (for example from the FT232's 3.3V regulator)

* Connect the following pins

    FT232   ATMEGA  PIN
    --------------------
    D4      TMS     26
    D2      TDI     28
    D3      TDO     27
    D5      TCK     25
    GND     GND     20

* Run the programming command, substituting your .elf file for main.elf

    $ python program.py main.elf

