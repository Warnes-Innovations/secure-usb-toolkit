DEVICE ?= /dev/sdX
SRC    ?= /dev/sdX
DST    ?= /dev/sdY

.PHONY: tui cli container usb populate clone verify dist

tui:
	python3 tui.py

cli:
	python3 cli.py $(ARGS)

container:
	cd build && ./create_container.sh

usb:
	@python3 -c "from build import safety; safety.print_disks(); safety.confirm_device('$(DEVICE)')"
	cd build && ./create_usb_layout.sh $(DEVICE)

populate:
	cd build && ./populate_tools_partition.sh /mnt/tools

clone:
	@python3 -c "from build import safety; safety.print_disks(); safety.confirm_device('$(DST)')"
	cd build && ./clone_usb.sh $(SRC) $(DST)

verify:
	cd build && ./verify.sh

dist:
	mkdir -p dist
	pyinstaller --onedir --name SecureUSB --distpath dist tui.py
	cp launchers/SecureUSB.command dist/
	cp launchers/SecureUSB.sh dist/
	cp launchers/SecureUSB.bat dist/
	chmod +x dist/SecureUSB.command dist/SecureUSB.sh
