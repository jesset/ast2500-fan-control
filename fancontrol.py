#!/usr/bin/python3
import shutil
import subprocess
import re
import time

import numpy as np

ipmitool = shutil.which("ipmitool")  # path to ipmitool (Fan speed monitoring/control)
smartctl = shutil.which("smartctl") # path to smartctl (HDD temperature)
smi = shutil.which("nvidia-smi")     # path to nvidia-smi (GPU temperature/activity)
lsblk = shutil.which("lsblk")        # path to lsbl
# lmSensors = shutil.which("sensors")  # path to sensors (CPU temperature)

hddCheckInterval = 120
cpuCheckInterval = 30

# Gets a list of hdds
# Only get hdds (lsblk -I 8) and ignore partitions
hdds = []
hddList = subprocess.check_output([lsblk,"-o","NAME","-nl","-I","8","-d"]).decode("utf-8").split("\n")[:-1]
for i in hddList:
    hdds.append("/dev/{0}".format(i))

# Current fan speed: ipmitool raw 0x3a 0x02
# fan map: (E3C246D4U2-2T)
# ipmitool raw 0x3a 0x01    0x64       0x64    0x64    0x64    0x64       0x64        0x64       0x64
#                           CPU_FAN1   none    none    none    FRNT_FAN1  FRNT_FAN2   FRNT_FAN3  none


# Object contains the temperature settings for each fan speed
tempPoints = {
    "cpu": [40, 50, 60, 80],
    "hdds": [20, 38, 40, 45, 50],
    "nvme": [40, 50, 60, 70],
    "none": [0, 0, 0]
}

# Object contains the fan speed settings for each component
fanSpeedPoints = {
    "cpu": [20, 30, 40, 100],
    "hdds": [40, 65, 80, 90, 100],
    "nvme": [20, 30, 50, 80],
    "none": [100, 100, 100]
}

# The current, minimum, and maximum fan speeds
fanSpeeds = {
    "current" : [0,0,0,0,0,0,0,0]
}

# # Regex for each fan
# fanSpeedRe = [
#     r"^CPU_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
#     r"^REAR_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
#     r"^FRONT_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
#     r"^FRONT_FAN2.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
#     r"^FRONT_FAN3.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
#     r"^FRONT_FAN4.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$"
# ]

fanMap = ["cpu", "none", "none", "none", "hdds", "hdds", "nvme", "none"]
# fan map: FRNT_FAN1, REAR_FAN1(none), CPU_FAN1, FRNT_FAN3(chassis), FRNT_FAN2, REAR_FAN2(none)

# Current temperature readings
# cpu, hdd, nvme
tempReadings = [100,100,100]


# def getFanSpeeds():
#     try:
#         # Checks each fan speed and puts it into the current fan speed array
#         for i in range(len(fanSpeeds["current"])):
#             fanSpeeds["current"][i] = re.search(re.compile(fanSpeedRe[i], re.MULTILINE),subprocess.check_output([ipmitool,'sdr','type','Fans']).decode('utf-8')).group(1)

#         return fanSpeeds
#     except Exception as e:
#         print(f"exception in get_cpu_fan_speed: {e}")

def getTemps():
    global tempReadings
    try:
        # Get CPU temperature
        tempReadings[0] = int(re.search(re.compile(r'^CPU\sTemp.*\|\s([0-9][0-9])\sdegrees\sC$', re.MULTILINE),subprocess.check_output([ipmitool,'sdr','type','Temperature']).decode('utf-8')).group(1))
        print(f"INFO: CPU Temperature: {tempReadings[0]}")

        # Get GPU temperature
        # tempReadings[2] = int(subprocess.check_output([smi,"--query-gpu=temperature.gpu","--format=csv,noheader"]).decode("utf-8"))
        # print(f"INFO: GPU Temperature: {tempReadings[2]}")

        # Get NVME ssd temperature
        nvme_disk = '/dev/nvme1'
        tempReadings[2] = int(re.search(re.compile(r'^Temperature:\s+(\d+)\s*Celsius$', re.MULTILINE),subprocess.check_output([smartctl,'-a',nvme_disk,'-d','nvme']).decode('utf-8')).group(1))
        print(f"INFO: NVMe Disk {nvme_disk}, Temperature: {tempReadings[2]}")

        return None

    except Exception as e:
        print(f"WARN: exception in getTemps: {e}")
        # TODO set all fans to full
        print(f"WARN: temp detection failure, all fans set to 100%")

def getHddTemps():
    global tempReadings
    try:
        hddTemps = [0] * len(hdds)

        # Get HDD temperatures
        for h in range(len(hdds)):
            try:
                hddProc = subprocess.check_output([smartctl,"-a",hdds[h]]).decode("utf-8")
                hddTemps[h] = int(re.search(re.compile(r"^.*194\sTemp.*\s(\d+)(?:\s[\(][^)]*[\)])?$", re.MULTILINE), hddProc).group(1))
                print(f"INFO: HDD {hdds[h]}, Temperature: {hddTemps[h]}")
            except:
                hddTemps[h] = 0

        # And get the hottest drive
        tempReadings[1] = max(hddTemps)

        return None

    except Exception as e:
        print(f"WARN: exception in getHddTemps: {e}")
        # TODO set all fans to full
        print(f"WARN: temp detection failure, all fans set to 100%")

def calcFanSpeed(temp, tempPoints, fanSpeedPoints):
    if temp < min(tempPoints):
        return 1
    elif temp > max(tempPoints):
        return 100
    else:
        return int(np.interp(temp, tempPoints, fanSpeedPoints))

def setFanSpeed():
    global fanSpeeds
    fanSpeedHex = ["0x64"] * (len(fanSpeeds["current"]))

    # for each temperature, calculate the required fan speed
    for i in range(len(fanMap)):
        # Maps each fan to it's relevant temperature reading
        if fanMap[i] == "cpu":
            tempReading = tempReadings[0]
        elif fanMap[i] == "hdds":
            tempReading = tempReadings[1]
        elif fanMap[i] == "nvme":
            tempReading = tempReadings[2]
        else:
            # If it's a fan that's not connected just set it to 100
            tempReading = 100

        fanSpeeds["current"][i] = calcFanSpeed(tempReading, tempPoints[fanMap[i]], fanSpeedPoints[fanMap[i]])
        fanSpeedHex[i] = str(hex(fanSpeeds["current"][i]))

    # And finally set all the fans
    subprocess.check_output([ipmitool,"raw","0x3a","0x01"]+fanSpeedHex)
    print([ipmitool,"raw","0x3a","0x01"]+fanSpeedHex)

    return None


hddLastChecked = time.time()

if __name__ == "__main__":
    print(f"INFO: ipmitool executable at {ipmitool}")
    print(f"INFO: smartctl executable at {smartctl}")
    print(f"INFO: initial hard drives: {', '.join(hdds)}")

    getHddTemps()
    while True:
        getTemps()

        if time.time() - hddLastChecked >= hddCheckInterval:
            getHddTemps()

        setFanSpeed()

        time.sleep(cpuCheckInterval)
