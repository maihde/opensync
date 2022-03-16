OpenSync
========

Hardware
--------

* [Raspberry Pi](https://www.raspberrypi.org/) with microSD card.
* [Blues Wireless Notecard and Notecarrier Pi](https://shop.blues.io/collections/development-kits/products/raspberry-pi-starter-kit)
* [Raspberry Pi UPS HAT](https://www.pishop.us/product/raspberry-pi-ups-hat/)
* [ezShare WiFi SD Card Adapter](https://us.amazon.com/Share-Wifi-Memory-Adapter-available/dp/B00H4A6TGI)
* Optional [Cirocomm 5cm Active GPS Antenna](https://www.amazon.com/gp/product/B078Y2WNY6)

Assemble the Raspberry Pi on the bottom, Notecarrier (with installed Notecard) in the middle,
and the Pi UPS HAT on the top.


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
7. Enable i2c by running `sudo raspi-config` and selecting **Interface Options** and then **I2D**
8. Setup ez Share WiFi by running `sudo raspi-config` and selection **System Options** and **Wireless LAN**.  The default SSID is "ez Share" and the default password is "88888888".
9. Execute the following commands:

```
$ sudo wpa_cli -i wlan0 reconfigure
$ sudo apt-get update
$ sudo apt-get install python3-venv git python3-numpy python3-pandas i2c-tools
$ python -m venv --system-site-packages OpenSync
$ . OpenSync/bin/activate
$ python -m pip install git+https://github.com/maihde/opensync.git
$ sudo cp OpenSync/etc/opensync.service /etc/systemd/system/opensync.service
$ sudo cp ups.sh /etc/init.d; sudo chmod a+x /etc/init.d/ups.sh
$ sudo update-rc.d ups.sh defaults
$ echo 'product: "YOUR_NOTE_HUB_PRODUCT"' >> ~/OpenSync/etc/opensync.conf
$ sudo systemctl enable opensync
$ sudo systemctl start opensync
```


Logs
------------
Logs will be sent to `/var/log/daemon.log`.