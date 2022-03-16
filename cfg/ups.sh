#GPIO17 (input) used to read current power status.
#0 - normal (or battery power switched on manually).
#1 - power fault, swithced to battery.
if ! [ -e /sys/class/gpio/gpio17 ]; then
    echo 17 > /sys/class/gpio/export;
fi
echo in > /sys/class/gpio/gpio17/direction;

#GPIO27 (input) used to indicate that UPS is online
if ! [ -e /sys/class/gpio/gpio27 ]; then
    echo 27 > /sys/class/gpio/export;
fi
echo in > /sys/class/gpio/gpio27/direction;

#GPIO18 used to inform UPS that Pi is still working. After power-off this pin returns to Hi-Z state.
if ! [ -e /sys/class/gpio/gpio18 ]; then
    echo 18 > /sys/class/gpio/export;
fi
echo out > /sys/class/gpio/gpio18/direction;
echo 0 > /sys/class/gpio/gpio18/value;