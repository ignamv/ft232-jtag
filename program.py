#!/usr/bin/env python3

from pylibftdi import BitBangDevice
from pylibftdi.driver import BITMODE_SYNCBB
from time import sleep

import argparse
parser = argparse.ArgumentParser(description=
    'Program ATMEGA162 through JTAG interface connected to an FT232R')
parser.add_argument('--noverify', action='store_true',
    help='Do not verify after programming')
parser.add_argument('elffile', help='.elf file to program in FLASH')
args = parser.parse_args()

dev = BitBangDevice(bitbang_mode=BITMODE_SYNCBB)
TMS = 1 << 4
TDI = 1 << 2
TDO = 1 << 3
TCK = 1 << 5
dev.direction = TMS | TDI | TCK

from math import ceil
from enum import Enum
def jtag_command(instruction, data):
    """Set the instruction register, shift in bits from data, return the output bits
    data[0] holds the least significant bits"""
    if not isinstance(instruction, AVR_JTAG):
        raise ValueError("instruction must be member of AVR_JTAG")
    irvalue = instruction.value[0]
    nbits = instruction.value[1]
    if isinstance(data, int):
        data = data.to_bytes(ceil(nbits/8), 'little')
    stream = [0]
    IR_LENGTH = 4
    def clock_in(bits):
        """Output bits then raise TCK. 
        Returns index of (input state after the rising TCK edge) in the response array."""
        stream.append(bits)
        stream.append(bits+TCK)
        return len(stream)
    # Take TAP controller from Test-Logic-Reset to Run-Test/Idle
    for ii in range(2):
        clock_in(0)
    # Take TAP to Shift-IR
    for tms in [1,1,0,0]:
        clock_in(tms * TMS)
    # Shift IDCODE (0x1) into IR
    for bit in range(IR_LENGTH):
        clock_in((irvalue & 1) * TDI)
        irvalue >>= 1
    # MSB of IR is shifted with TMS high
    stream[-2] |= TMS
    stream[-1] |= TMS
    # Take TAP to Run-Test/Idle, then Shift-DR
    for tms in [1,0,1,0,0]:
        clock_in(tms * TMS)
    # Shift out nbits of data register
    # data[0] is LSB
    retindex = None
    for bit in range(nbits):
        byte = int(bit / 8)
        if byte < len(data):
            ret = clock_in(TDI*bool(
                (data[byte] >> (bit%8)) & 1))
        else:
            # Pad with zeros
            ret = clock_in(0)
        if bit == 0:
            retindex = ret
        #data[int(bit / 8)] >>= 1
    # MSB of DR is shifted with TMS high
    stream[-2] |= TMS
    stream[-1] |= TMS
    # Take TAP to Run-Test/Idle
    for tms in [1,0]:
        clock_in(tms * TMS)
    clock_in(0)
    dev.flush()
    # Return buffer
    bytes = bytearray(ceil(nbits / 8))
    CHUNK_SIZE = 256
    read = []
    for offset in range(0, len(stream), CHUNK_SIZE):
        written = dev.write(bytearray(stream[offset:offset+CHUNK_SIZE]))
        read.append(dev.read(written))
    ret = b''.join(read)
    for bit in range(nbits):
        bytes[int(bit / 8)] |= bool(ret[retindex + 2 * bit] & TDO) << (bit % 8)
    return bytes
class AVR_JTAG(Enum):
    # (instruction register value, number of bits in selected data register)
    IDCODE        = (0x1, 32)
    PROG_ENABLE   = (0x4, 16)
    PROG_COMMANDS = (0x5, 15)
    PROG_PAGELOAD = (0x6, 1024)
    PROG_PAGEREAD = (0x7, 1032)
    AVR_RESET     = (0xC, 1)
    BYPASS        = (0xF, 1)

from elftools.elf.elffile import ELFFile
def program_elf(file, verify=True):
    """Write executable into atmega162 program memory. Example:
    
        >>> program('elffile')
    """
    elf = ELFFile(open(file, 'rb'))
    program = elf.get_section_by_name(b'.text').data()
    jtag_command(AVR_JTAG.AVR_RESET, 1)
    jtag_command(AVR_JTAG.PROG_ENABLE, 0xA370)
     # Chip Erase
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x2380)
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3180)
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3380) 
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3380)
    sleep(10e-3) # Wait for chip erase
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x2310) # Enter Flash Write
    PAGE_BYTES = int(1024 / 8)
    for offset in range(0, len(program), PAGE_BYTES):
        address = offset >> 1 # Flash words are 2 bytes
        jtag_command(AVR_JTAG.PROG_COMMANDS, 0x0700 | (address>>8) & 0xff) # Load Address High Byte
        jtag_command(AVR_JTAG.PROG_COMMANDS, 0x0300 | address & 0xff) # Load Address Low Byte
        jtag_command(AVR_JTAG.PROG_PAGELOAD, program[offset:offset+PAGE_BYTES])
         # Write Flash Page
        jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700)
        jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3500)
        jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700)
        jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700)
        sleep(10e-3) # Wait for Flash write
    if verify:
        jtag_command(AVR_JTAG.PROG_COMMANDS, 0x2302) # Enter Flash Read
        for offset in range(0, len(program), PAGE_BYTES):
            address = offset >> 1 # Flash words are 2 bytes
            jtag_command(AVR_JTAG.PROG_COMMANDS, 0x0700 | (address>>8) & 0xff) # Load Address High Byte
            jtag_command(AVR_JTAG.PROG_COMMANDS, 0x0300 | address & 0xff) # Load Address Low Byte
            read = jtag_command(AVR_JTAG.PROG_PAGEREAD, 0)[1:]
            if read[:len(program)-offset] != program[offset:offset+PAGE_BYTES]:
                raise RuntimeError('Verification failed at offset {}: wrote {}, read {}'.format(
                    offset, program[offset:offset+PAGE_BYTES], read))
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x2300) # Exit Programming Mode
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3300) # Exit Programming Mode
    jtag_command(AVR_JTAG.PROG_ENABLE, 0)
    jtag_command(AVR_JTAG.AVR_RESET, 0)

def poll_fuse_write_complete():
    while True:
        if jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700)[1] & 2:
            break
def program_fuses(fuses, extended_fuses):
    if not isinstance(fuses, int):
        raise TypeError('Expected int for fuses')
    jtag_command(AVR_JTAG.AVR_RESET, 1)
    jtag_command(AVR_JTAG.PROG_ENABLE, 0xA370)
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x2340) # Enter Fuse Write
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x1300 | (extended_fuses & 0xff)) # Load Data Low Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3b00) # Write Fuse Extended Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3900) # Write Fuse Extended Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3b00) # Write Fuse Extended Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3b00) # Write Fuse Extended Byte
    poll_fuse_write_complete()
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x1300 | ((fuses >> 8) & 0xff)) # Load Data Low Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700) # Write Fuse High Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3500) # Write Fuse High Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700) # Write Fuse High Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700) # Write Fuse High Byte
    poll_fuse_write_complete()
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x1300 | (fuses & 0xff)) # Load Data Low Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3300) # Write Fuse High Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3100) # Write Fuse High Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3300) # Write Fuse High Byte
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3300) # Write Fuse High Byte
    poll_fuse_write_complete()
def read_fuses_locks():
    jtag_command(AVR_JTAG.AVR_RESET, 1)
    jtag_command(AVR_JTAG.PROG_ENABLE, 0xA370)
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x2304) # Enter Fuse/Lock Bit Read
    jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3a00) # Read fuses and lock bits
    extended = jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3e00)[0] # Read fuses and lock bits
    high = jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3200)[0] # Read fuses and lock bits
    low = jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3600)[0] # Read fuses and lock bits
    lock = jtag_command(AVR_JTAG.PROG_COMMANDS, 0x3700)[0] # Read fuses and lock bits
    return extended, high << 8 | low, lock

program_elf(args.elffile, verify=not args.noverify)
