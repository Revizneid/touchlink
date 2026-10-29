# Wake-on-LAN and resume flow

## Overview

TouchLink uses a fail-closed wake policy: a device can only request wake for a known MAC address when it has the `wake` permission and the target is in the trusted device set.

## Magic packet format

The Wake-on-LAN magic packet has this structure:

- 6 bytes of `0xFF`
- repeated 16 times for the target MAC address

For example, for `00:11:22:33:44:55`, the packet is 102 bytes long:

- 6 bytes sync
- 16 copies of 6 bytes of the MAC

This is the standard packet used by NICs that support WoL.

## Security notes

- The request must contain a valid target MAC address.
- The request must include the `wake` permission flag.
- This module does not send packets directly; the real LAN helper should use the validated request to send the packet through a trusted local host or relay helper.
- The target must be explicitly authorized and the wake request should be rate-limited.

## Windows setup

To enable Wake-on-LAN on a desktop PC:

1. Enable WoL in BIOS/UEFI.
2. Enable Wake on Magic Packet in the network adapter properties.
3. In Windows, allow the adapter to wake the computer.
4. Disable Fast Startup if the machine does not wake consistently.
5. Ensure the adapter can receive the magic packet while the machine is suspended.

## Resume path

When a mobile PWA connection is interrupted, the app should continue using the existing `resume_token` flow instead of forcing the user to re-enter credentials. This keeps the reconnect path fast on iOS Safari and Android Chrome.
