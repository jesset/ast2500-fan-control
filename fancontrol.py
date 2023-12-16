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

hddCheckInterval = 60
cpuCheckInterval = 5

# Gets a list of hdds
# Only get hdds (lsblk -I 8) and ignore partitions
hdds = []
hddList = subprocess.check_output([lsblk,"-o","NAME","-nl","-I","8","-d"]).decode("utf-8").split("\n")[:-1]
for i in hddList:
    hdds.append("/dev/{0}".format(i))

# Current fan speed: ipmitool raw 0x3a 0x02
# fan map: cpu, nc, rear_fan1(exhaust), nc, front_fan1(hdds), front_fan2(gpu), front_fan3(none), front_fan4 (uncontrolled, chipset)

# Object contains the temperature settings for each fan speed
tempPoints = {
    "cpu": [40, 60, 80],
    "hdds": [20, 37, 45, 50],
    "gpu": [50, 60, 70],
    "none": [0, 0, 0]
}

# Object contains the fan speed settings for each component
fanSpeedPoints = {
    "cpu": [25, 50, 100],
    "hdds": [15, 35, 50, 100],
    "gpu": [25, 50, 100],
    "none": [100, 100, 100]
}

# The current, minimum, and maximum fan speeds
# cpu, nc, rear, nc, front1, front2, front3, front4
# cpu, nc, rear, nc, front,  gpu,    none,   chipset
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

fanMap = ["cpu", "none", "hdds", "none", "hdds", "gpu", "none", "none"]

# Current temperature readings
# cpu, hdd, gpu
tempReadings = [100,100,100]

# get each hdd temperature
# #!/bin/bash
# DRIVEPATH="$1"
# INFO="$(sudo smartctl -a $DRIVEPATH)"
# TEMP=$(echo "$INFO" | grep '194 Temp' | awk '{print $10}')
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep '190 Airflow' | awk '{print $10}')
# fi
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep 'Temperature Sensor 1:' | awk '{print $4}')
# fi
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep 'Current Drive Temperature:' | awk '{print $4}')
# fi
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep 'Temperature:' | awk '{print $2}')
# fi
# echo $TEMP


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
        
        # Get GPU temperature
        tempReadings[2] = int(subprocess.check_output([smi,"--query-gpu=temperature.gpu","--format=csv,noheader"]).decode("utf-8"))
        
        return None
        
    except Exception as e:
        print(f"exception in getTemps: {e}")
        # TODO set all fans to full
        print(f"temp detection failure, all fans set to 100%")
        
def getHddTemps():
    global tempReadings
    try:
        hddTemps = [0] * len(hdds)
        
        # Get HDD temperatures
        for h in range(len(hdds)):
            hddProc = subprocess.check_output([smartctl,"-a",hdds[h]]).decode("utf-8")
            try:
                hddTemps[h] = int(re.search(re.compile(r"^.*194\sTemp.*\s(\d+)(?:\s[\(][^)]*[\)])?$", re.MULTILINE), hddProc).group(1))
            except:
                hddTemps[h] = 0
        
        # And get the hottest drive
        tempReadings[1] = max(hddTemps)
        
        return None
        
    except Exception as e:
        print(f"exception in getHddTemps: {e}")
        # TODO set all fans to full
        print(f"temp detection failure, all fans set to 100%")

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
        elif fanMap[i] == "gpu":
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
    print(f"ipmitool executable at {ipmitool}")
    print(f"smartctl executable at {smartctl}")
    print(f"initial hard drives: {', '.join(hdds)}")

    getHddTemps()
    while True:
        getTemps()
        
        if time.time() - hddLastChecked >= hddCheckInterval:
            getHddTemps()
        
        setFanSpeed()
        
        time.sleep(cpuCheckInterval)
