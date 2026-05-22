"""WTP instance registry.

Each entry: (ObjectType, InstanceID, {attribute: generator})

Topic structure:    Plant/WTP/<ObjectType>/<InstanceID>/<Attribute>
OPC-UA path:        Objects/Plant/WTP/<ObjectType>/<InstanceID>/<Attribute>
"""

from generators import ob, rw

INSTANCES: list[tuple[str, str, dict]] = [
    # Raw water intake pumps
    ("Pump", "RawWater_01",    {"Flow": rw(0, 500, 4.0),  "Pressure": rw(0, 10, 0.08), "Running": ob(True,  0.01), "Power": rw(0, 75, 0.6)}),
    ("Pump", "RawWater_02",    {"Flow": rw(0, 500, 4.0),  "Pressure": rw(0, 10, 0.08), "Running": ob(True,  0.01), "Power": rw(0, 75, 0.6)}),
    # High-service distribution pumps
    ("Pump", "HighService_01", {"Flow": rw(0, 500, 3.5),  "Pressure": rw(2, 10, 0.06), "Running": ob(True,  0.01), "Power": rw(0, 75, 0.5)}),
    ("Pump", "HighService_02", {"Flow": rw(0, 500, 3.5),  "Pressure": rw(2, 10, 0.06), "Running": ob(False, 0.01), "Power": rw(0, 75, 0.5)}),
    # Clarifier and finished water storage
    ("Tank", "Clarifier_01",    {"Level": rw(0, 100, 0.5), "Turbidity": rw(0, 5, 0.03)}),
    ("Tank", "FinishedWater_01",{"Level": rw(0, 100, 0.4), "pH": rw(6.8, 7.8, 0.01), "Turbidity": rw(0, 1, 0.01)}),
    # Chemical dosing
    ("Dosing", "Chlorine_01",  {"FlowRate": rw(0, 10, 0.05), "Running": ob(True,  0.01), "TankLevel": rw(20, 100, 0.2)}),
    ("Dosing", "Fluoride_01",  {"FlowRate": rw(0, 10, 0.04), "Running": ob(True,  0.01), "TankLevel": rw(20, 100, 0.2)}),
    # UV disinfection banks
    ("UV", "UV_01", {"Intensity": rw(85, 100, 0.3), "Running": ob(True,  0.005), "LampHours": rw(0, 10000, 0.01)}),
    ("UV", "UV_02", {"Intensity": rw(85, 100, 0.3), "Running": ob(False, 0.005), "LampHours": rw(0, 10000, 0.01)}),
]
