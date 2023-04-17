#!/usr/bin/python3
import shutil
import subprocess
import re
import time
import datetime

import numpy as np

ipmitool = shutil.which("ipmitool")  # path to ipmitool (Fan speed monitoring/control)
smartctl = shutil.which("smartctl") # path to smartctl (HDD temperature)
smi = shutil.which("nvidia-smi")     # path to nvidia-smi (GPU temperature/activity)
# lmSensors = shutil.which("sensors")  # path to sensors (CPU temperature)

hddCheckInterval = 60
cpuCheckInterval = 5

# list of disks to poll for temperature
hdds = ['/dev/sda','/dev/sdb','/dev/sdc','/dev/sdd']

# Current fan speed: ipmitool raw 0x3a 0x02
# fan map: cpu, nc, rear_fan1(exhaust), nc, front_fan1(gpu), front_fan2(top hd), front_fan3(bottom hd), front_fan4 (uncontrolled, chipset)

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
# cpu, nc, rear, nc, gpu,    top,    bottom, chipset
fanSpeeds = {
    "current" : [0,0,0,0,0,0,0,0],
    "min" : [1,1,1,1,1,1,1,1],
    "max" : [2,2,2,2,2,2,2,2]
}

# Regex for each fan
fanSpeedRe = [
    r"^CPU_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^REAR_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN2.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN3.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN4.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$"
]

fanMap = ["cpu", "none", "hdds", "none", "gpu", "hdds", "hdds", "none"]

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

# various globals
# hdFanSpeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]

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
        tempReadings[0] = re.search(re.compile(r'^CPU\sTemp.*\|\s([0-9][0-9])\sdegrees\sC$', re.MULTILINE),subprocess.check_output([ipmitool,'sdr','type','Temperature']).decode('utf-8')).group(1)
        
        # Get GPU temperature
        tempReadings[2] = subprocess.check_output([smi,"--query-gpu=temperature.gpu","--format=csv,noheader"]).decode("utf-8")
        
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
            hddProc = subprocess.check_output([smartctl],"-a",hdds[h])
            hddTemps[h] = re.search(re.compile(r"^.*194\sTemp.*\s([0-9][0-9])$", re.MULTILINE), hddProc).group(1)
        # And get the hottest drive
        tempReadings[1] = max(hddTemps)
        
        return None
        
    except Exception as e:
        print(f"exception in getHddTemps: {e}")
        # TODO set all fans to full
        print(f"temp detection failure, all fans set to 100%")

def calcFanSpeed(temp, tempPoints, fanSpeedPoints):
    if temp < min(tempPoints):
        return 0
    elif temp > max(tempPoints):
        return 100
    else:
        return np.interp(temp, tempPoints, fanSpeedPoints)

def setFanSpeed():
    global fanSpeeds
    fanSpeedHex = ["0x64"] * (len(fanSpeeds))
    
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
    
    return None

hddLastChecked = time.time()

if __name__ == "__main__":
    print(f"ipmitool executable at {ipmitool}")
    print(f"smartctl executable at {smartctl}")
    print(f"initial hard drives: {', '.join(hdds())}")
    
    while True:
        getTemps()
        
        if time.time() - hddLastChecked >= hddCheckInterval:
            tempReadings[1] = getHddTemps()
        
        setFanSpeed()
        
        time.sleep(cpuCheckInterval)

# def checkcputemp():
#     global currentcpufanspeed
#     global cpuoverride
#     try:
#         currentcputemp = getcputemp()
#         if currentcputemp > cpu_override_temp and cpuoverride == False:
#             subprocess.run(allfanshigh)
#             cpuoverride = True
#             log('cpu temp > '+str(cpu_override_temp)+'C, all fans set to 100%')
#         elif currentcputemp < cpu_normal_temp and cpuoverride == True:
#             subprocess.run(hdfanspeed)
#             cpuoverride = False
#             log('cpu temp < '+str(cpu_normal_temp)+'C, cpu fan set to '+str(cpu_fan_default)+'%')
#     except Exception as e:
#         log(e)

# def hdtemp(dev):
#     try:
#         temp = subprocess.check_output([hddtemp,dev])
#         temp = re.match('^.*([0-9][0-9])°C$', temp.decode('utf-8'))
#         temp = temp.group(1)
#         return temp
#     except Exception as e:
#         log(e)
#         subprocess.run(allfanshigh)
#         log('hd temp detection failure, all fans set to 100%')

# def checkhdtemps():
#     hdtemps = []
#     global hdchecktime
#     global currenthdfanspeed
#     global hdfanspeed
#     if cpuoverride == False:
#         try:
#             for hdd in hdds:
#                 hdtemps.append(int(hdtemp(hdd)))
#             if any(x >= hd_hi for x in hdtemps):
#                 currenthdfanspeed = hex(hd_fans_hi)
#                 hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
#                 subprocess.run(hdfanspeed)
#                 log('hd temp >= '+str(hd_hi)+',C fans set to '+str(hd_fans_hi)+'%')
#             elif any(x == hd_medhi for x in hdtemps):
#                 currenthdfanspeed = hex(hd_fans_medhi)
#                 hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
#                 subprocess.run(hdfanspeed)
#                 log('hd temp '+str(hd_medhi)+',C fans set to '+str(hd_fans_medhi)+'%')
#             elif any(x == hd_medlo for x in hdtemps):
#                 currenthdfanspeed = hex(hd_fans_medlo)
#                 hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
#                 subprocess.run(hdfanspeed)
#                 log('hd temp '+str(hd_medlo)+'C, fans set to '+str(hd_fans_medlo)+'%')
#             elif all(x <= hd_lo for x in hdtemps):
#                 currenthdfanspeed = hex(hd_fans_lo)
#                 hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
#                 subprocess.run(hdfanspeed)
#                 log('hd temp <= '+str(hd_lo)+'C, fans set to '+str(hd_fans_lo)+'%')
#         except Exception as e:
#             log(e)
#     else:
#         log('cpu temp override active, no action taken on hd fans')
#     hdchecktime = time.time()

# checkhdtemps()
