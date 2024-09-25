import obd
import sys
import asyncio
import socket
from serial.tools import list_ports
from obd import OBDCommand
from obd.utils import bytes_to_int

# Define custom commands for torque
def decode_percent_torque(messages):
    if not messages:
        return None
    msg = messages[0]
    A = bytes_to_int(msg.data[0])
    torque_percent = A - 125  # Value ranges from -125% to 125%
    return torque_percent  # Return as float without units

def decode_reference_torque(messages):
    if not messages:
        return None
    msg = messages[0]
    A = bytes_to_int(msg.data[0])
    B = bytes_to_int(msg.data[1])
    torque = (A << 8) + B  # Value in Nm
    return torque  # Return as float without units

# Create custom OBD commands
ACTUAL_ENGINE_PERCENT_TORQUE = OBDCommand(
    "ACTUAL_ENGINE_PERCENT_TORQUE",   # Name
    "Actual Engine Percent Torque",   # Description
    b"0162",                          # Command PID
    1,                                # Number of expected bytes
    decode_percent_torque,             # Decoder function
    fast=True
)

ENGINE_REF_TORQUE = OBDCommand(
    "ENGINE_REF_TORQUE",              # Name
    "Engine Reference Torque",        # Description
    b"0163",                          # Command PID
    2,                                # Number of expected bytes
    decode_reference_torque,           # Decoder function
    fast=True
)

def connect_obd():
    # Scan for serial ports (USB and Bluetooth)
    serial_ports = [port.device for port in list_ports.comports()]
    print("Available serial ports:", serial_ports)

    connection = None

    # Try connecting via serial ports
    for port in serial_ports:
        try:
            print(f"Trying serial port {port}")
            connection = obd.Async(port, baudrate=9600, fast=True)
            if connection.is_connected():
                print(f"Connected to OBD-II device on serial port {port}")
                return connection
        except Exception as e:
            print(f"Failed to connect on serial port {port}: {e}")
            continue

    # If serial connection fails, try common WiFi addresses
    wifi_addresses = [
        ('192.168.0.10', 35000),
        ('192.168.0.10', 23),
        ('192.168.0.11', 35000),
        ('192.168.0.123', 35000),
    ]

    for ip, port in wifi_addresses:
        try:
            print(f"Trying WiFi address {ip}:{port}")
            sock = socket.create_connection((ip, port), timeout=2)
            sock.close()
            connection = obd.Async(f"socket://{ip}:{port}", baudrate=None, protocol=None, fast=True)
            if connection.is_connected():
                print(f"Connected to OBD-II device at {ip}:{port}")
                return connection
        except Exception as e:
            print(f"Failed to connect to WiFi OBD-II device at {ip}:{port}: {e}")
            continue

    print("Could not connect to any OBD-II device.")
    sys.exit(1)

async def main():
    connection = connect_obd()
    if connection is None:
        print("Failed to connect to OBD-II device.")
        return

    # Enable batch querying if supported
    if connection.supports_multiple_commands:
        connection.supports_multiple_commands = True

    # Register custom commands
    obd.commands.add_custom(ACTUAL_ENGINE_PERCENT_TORQUE)
    obd.commands.add_custom(ENGINE_REF_TORQUE)

    # Check if the required PIDs are supported
    required_commands = [
        obd.commands.RPM,
        ACTUAL_ENGINE_PERCENT_TORQUE,
        ENGINE_REF_TORQUE,
    ]

    unsupported_commands = [cmd for cmd in required_commands if not connection.supports(cmd)]
    if unsupported_commands:
        print("The following required PIDs are not supported by your vehicle:")
        for cmd in unsupported_commands:
            print(f"- {cmd.name}")
        print("Cannot calculate horsepower based on RPM and Torque.")
        sys.exit(1)

    # Variables to hold data
    data = {'RPM': None, 'Torque_Percent': None, 'Reference_Torque': None}

    def process_data():
        if data['RPM'] is not None and data['Torque_Percent'] is not None and data['Reference_Torque'] is not None:
            # Calculate actual torque in Nm
            actual_torque_nm = (data['Torque_Percent'] / 100.0) * data['Reference_Torque']

            # Calculate horsepower
            horsepower = (actual_torque_nm * data['RPM']) / 7127  # Conversion factor for Nm and RPM to HP

            print(f"RPM: {data['RPM']:.2f} RPM")
            print(f"Torque: {actual_torque_nm:.2f} Nm")
            print(f"Horsepower: {horsepower:.2f} HP")
            print("-" * 30)

    # Define callbacks
    def new_rpm(r):
        if not r.is_null():
            data['RPM'] = r.value.magnitude
            process_data()

    def new_torque_percent(r):
        if r.value is not None:
            data['Torque_Percent'] = r.value  # Already a float
            process_data()

    def new_reference_torque(r):
        if r.value is not None:
            data['Reference_Torque'] = r.value  # Already a float
            process_data()

    # Subscribe to the required PIDs
    connection.watch(obd.commands.RPM, callback=new_rpm)
    connection.watch(ACTUAL_ENGINE_PERCENT_TORQUE, callback=new_torque_percent)
    connection.watch(ENGINE_REF_TORQUE, callback=new_reference_torque)

    # Set a custom polling interval (e.g., 0.1 seconds)
    connection.set_poll_interval(0.1)  # Poll every 100ms
    connection.start()

    # Wait indefinitely
    try:
        await asyncio.Event().wait()  # This will wait forever
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        connection.stop()

def self_test():
    # Simulate data
    data = {
        'RPM': 3000.0,             # RPM
        'Torque_Percent': 50.0,    # Percent
        'Reference_Torque': 300.0  # Nm
    }

    actual_torque_nm = (data['Torque_Percent'] / 100.0) * data['Reference_Torque']
    horsepower = (actual_torque_nm * data['RPM']) / 7127

    print("Self-test results:")
    print(f"RPM: {data['RPM']:.2f} RPM")
    print(f"Torque Percent: {data['Torque_Percent']:.2f}%")
    print(f"Reference Torque: {data['Reference_Torque']:.2f} Nm")
    print(f"Actual Torque: {actual_torque_nm:.2f} Nm")
    print(f"Horsepower: {horsepower:.2f} HP")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        self_test()
    else:
        asyncio.run(main())
