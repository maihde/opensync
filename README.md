OpenSync
========

Hardware
--------

* [Raspberry Pi](https://www.raspberrypi.org/) with microSD card.
* [Blues Wireless Notecard and Notecarrier Pi](https://shop.blues.io/collections/development-kits/products/raspberry-pi-starter-kit)
* [Raspberry Pi UPS HAT](https://www.pishop.us/product/raspberry-pi-ups-hat/)
* [ezShare WiFi SD Card Adapter](https://us.amazon.com/Share-Wifi-Memory-Adapter-available/dp/B00H4A6TGI)
* [Toshiba Flash Air W-04 WiFi SD Card Adapter](https://www.amazon.com/Toshiba-FlashAir-W-04-Class-Memory/dp/B0799JX7SW/ref=cm_cr_arp_d_product_top?ie=UTF8)
* Optional [Cirocomm 5cm Active GPS Antenna](https://www.amazon.com/gp/product/B078Y2WNY6)

Assemble the Raspberry Pi on the bottom, Notecarrier (with installed Notecard) in the middle,
and the Pi UPS HAT on the top.

IMPORTANT: Some (maybe all) Garmin G1000 units appear to be very particular about the SD card being used. The ezShare and early versions
of the Toshiba FlashAir (prior to W-04) do not work.

AWS Configuration
------------

This README assumes a basic familiarity with AWS services; the below steps are a general guide but omit some details for brevity.

1. Using SQS create a Queue
2. Using Lambda create a Lambda function using the contents of `lambda\lambda_function.py`
3. Setup SES to allow sending of e-mails

NoteHub Configuration
------------

Create a NoteHub Project following [these](https://dev.blues.io/notehub/notehub-walkthrough/#create-a-new-project) directions.  The project will
have a unique identifier (i.e. `YOUR_NOTE_HUB_PRODUCT`) that you will use later during configuration of OpenSync.

Once you have a NoteHub project, you will create two Routes: (1) a AWS route to SQS for `data.qo` Notefiles and (2) a Proxy Route to Savvy Analysis.

Installation
------------

1. [Download Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Select **Raspberry Pi OS (other)** and choose **Raspberry Pi OS Lite (32-bit)**
3. Press **Ctrl-Shift-X** to display advanced options.  Set hostname to **opensync** and select **Enable SSH** and provide a password.
4. Write the image to the SD card and install the SD card into the Raspberry Pi
5. Connect the Raspberry Pi Ethernet port to your network
6. Power on the Raspberry Pi and login with a username of 'pi' and the password set in step 3.
7. Enable i2c by running `sudo raspi-config` and selecting **Interface Options** and then **I2C**
8. Setup SD card WiFi by running `sudo raspi-config` and selection **System Options** and **Wireless LAN**.
9. Execute the following commands:

```
$ sudo wpa_cli -i wlan0 reconfigure
$ sudo apt-get update
$ sudo apt-get install python3-venv git python3-numpy python3-pandas i2c-tools
$ python -m venv --system-site-packages OpenSync
$ . OpenSync/bin/activate
$ python -m pip install git+https://github.com/maihde/opensync.git
$ sudo cp OpenSync/etc/opensync.service /etc/systemd/system/opensync.service
$ sudo cp OpenSync/etc/ups.sh /etc/init.d; sudo chmod a+x /etc/init.d/ups.sh
$ sudo update-rc.d ups.sh defaults
$ echo 'product: "YOUR_NOTE_HUB_PRODUCT"' >> ~/.opensync.conf
$ vi ~/OpenSync/etc/opensync.conf # edit to your preference
$ sudo systemctl enable opensync
$ sudo systemctl start opensync
$ sudo timedatectl set-timezone UTC
```

At this point the Raspberry Pi will try to connect to the WiFi SD card. If you need to make updates or other changes, you will need to connect the Raspberry Pi
to a wired network or use a serial console.

To update OpenSync

```
$ systemctl stop opensync
$ cp ~/OpenSync/etc/opensync.conf /var/tmp/opensync.conf
$ . OpenSync/bin/activate
$ python -m pip install --upgrade --force-reinstall --no-deps git+https://github.com/maihde/opensync.git
$ cp /var/tmp/opensync.conf ~/OpenSync/etc/opensync.conf 
$ systemctl start opensync
```

Logs
------------
Logs will be sent to `/var/log/daemon.log`.

Developer Notes
---------------

Running locally without a note-card or sd-card

```
PYTHONPATH=src python -m opensync --disable-notecard /path/to/file
```

Running locally without a note-card but using Toshiba FlashAir

```
PYTHONPATH=src python -m opensync --disable-notecard --wifi-sdcard=flashair
```

```
wget https://github.com/blues/note-go/releases/download/v1.4.9/notecardcli_linux_arm.tar.gz
sudo tar -xvzf notecardcli_linux_arm.tar.gz -C /usr/local/bin
```