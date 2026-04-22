import asyncio
import logging
import os
import socket
import random
import argparse
from pymodbus.server import StartAsyncTcpServer
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext

def parse_arguments():
    parser = argparse.ArgumentParser(description="Modbus Mirage - OT Virtual PLC")
    parser.add_argument("-i", "--ip", type=str, help="Bind IP address (e.g., 0.0.0.0 or 192.168.1.50)")
    parser.add_argument("-p", "--port", type=int, default=502, help="Modbus TCP Port (Default: 502)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Disable console UI for headless execution")
    return parser.parse_args()

def get_local_ip():
    ips = ["127.0.0.1"]
    
    try:
        hostname = socket.gethostname()
        _, _, host_ips = socket.gethostbyname_ex(hostname)
        for ip in host_ips:
            if ip not in ips:
                ips.append(ip)
    except socket.gaierror:
        pass

    # Dummy UDP socket to reliably determine the primary routing interface IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip not in ips:
            ips.append(primary_ip)
    except Exception:
        pass

    print("\n[*] Detected network interfaces:")
    for idx, ip in enumerate(ips):
        print(f"    - {ip}")
        
    print("\n[?] Enter the IP to bind the Virtual PLC.")
    print("    (Press Enter to use 127.0.0.1 by default)")
    
    chosen_ip = input(" > Bind IP: ").strip()
    
    if not chosen_ip:
        chosen_ip = "127.0.0.1"
        print(f"\n[!] No IP provided. Defaulting to: {chosen_ip}")
    else:
        print(f"\n[+] Selected IP: {chosen_ip}")
        
    return chosen_ip

logging.basicConfig()
log = logging.getLogger()
log.setLevel(logging.CRITICAL)

CLEAR_SCREEN = "\033[H\033[J"

def draw_ui(current_ip, port, identity, coils, regs, heartbeat, temp):
    print(CLEAR_SCREEN, end="")
    print("="*50)
    print("         █▀▀█ █  █ ▀▄ ▄▀    █▀▄ ▀▀█ █▄ █     ")
    print("          ▄▀  ▀▀▀█   █      █ █  ▀▄ █▀▄█     ")
    print("         █▄▄▄    █   █  ▄▄▄ █▄▀ ▄▄▀ █  █     ")
    print("               MODBUS MIRAGE PLC             ")
    print("="*50)
    print(f" [IP ADDR]       {current_ip} | PORT: {port}")
    print(f" [BIND MODE]     STRICT MODE")
    print(f" [VENDOR]        {identity.VendorName}")
    print(f" [MODEL]         {identity.ProductName}")
    print("-" * 50)
    print("\n [LIVE TELEMETRY (Input Regs)]")
    print(f" > Heartbeat (IR 0) : {heartbeat}")
    print(f" > Mq1 Temp  (IR 1) : {temp} °C")
    print("-" * 50)
    print("\n [EXPOSED MEMORY (Coils & Holdings)]")
    print(f" > COILS (0-15):     {[int(x) for x in coils]}")
    print(f" > HOLDING REGS:     {regs}")
    print("\n STATUS: LISTENING...")
    print("="*50)

async def monitor_plc(context, identity, current_ip, port, quiet):
    last_coils = []
    last_regs = []
    heartbeat_counter = 0
    base_temp = 450 
    
    if not quiet:
        draw_ui(current_ip, port, identity, [0]*16, [10, 20, 30, 40, 50], 0, 0)
    
    try:
        while True:
            slave = context[0x01] 
            
            heartbeat_counter = (heartbeat_counter + 1) % 65535
            fluctuation = random.randint(-15, 15)
            current_temp = base_temp + fluctuation
            
            # Write to Input Registers (Function 04) - Addresses 0 and 1
            slave.setValues(4, 0, [heartbeat_counter, current_temp])
            
            coils = slave.getValues(1, 0, count=16)
            regs = slave.getValues(3, 0, count=5)
            
            if not quiet:
                # Anti-flicker threshold: trigger UI update on state change or periodically for temperature
                if coils != last_coils or regs != last_regs or heartbeat_counter % 10 == 0:
                    last_coils = list(coils)
                    last_regs = list(regs)
                    display_temp = current_temp / 10.0
                    draw_ui(current_ip, port, identity, coils, regs, heartbeat_counter, display_temp)
            
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass 
    except Exception:
        pass 

async def run_server():
    args = parse_arguments()
    
    # CLI argument overrides interactive prompt
    current_ip = args.ip if args.ip else get_local_ip()
    port = args.port
    quiet = args.quiet

    # zero_mode=True aligns internal block memory with 0-based indexing requests
    store = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [0] * 100),
        co=ModbusSequentialDataBlock(0, [0] * 100),
        hr=ModbusSequentialDataBlock(0, [10, 20, 30, 40, 50] + [0]*95),
        ir=ModbusSequentialDataBlock(0, [0] * 100),
        zero_mode=True) 
    
    context = ModbusServerContext(slaves={0x01: store, 0x00: store}, single=False)

    identity = ModbusDeviceIdentification()
    identity.VendorName = 'Siemens'
    identity.ProductCode = 'SIMATIC S7-1200'
    identity.VendorUrl = 'https://www.siemens.com/'
    identity.ProductName = 'CPU 1214C'
    identity.MajorMinorRevision = 'V4.5'

    if not quiet:
        print(f"\n[*] Initiating strict bind on {current_ip}:{port}...")
    await asyncio.sleep(1) 
    
    monitor_task = asyncio.create_task(monitor_plc(context, identity, current_ip, port, quiet))

    try:
        await StartAsyncTcpServer(
            context=context, 
            identity=identity, 
            address=(current_ip, port),
            ignore_missing_slaves=True
        )
    except PermissionError:
        print("\n[!] ERROR: Permission denied.")
        print("[!] On Linux/macOS, root privileges (sudo) are required to bind to ports < 1024.")
        monitor_task.cancel()
    except OSError as e:
        print(f"\n[!] Network ERROR: {e}")
        print(f"[!] Verify that port {port} is not already in use by another service.")
        monitor_task.cancel()

if __name__ == "__main__":
    if os.name == 'nt':
        os.system('') # Enables ANSI escape sequences in Windows CMD
        
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\n[!] Server stopped by user.")