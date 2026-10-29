# Compatibility matrix

## Supported browser matrix

| Platform | Browser | Status | Notes |
| --- | --- | --- | --- |
| Android | Chrome 120+ | Supported | Use `playsinline`, `visualViewport` fallback, and `Wake Lock` when available. |
| Android | Samsung Internet | Supported | Similar to Chrome; keyboard resize handling still needed. |
| iOS | Safari 16+ | Supported with limitations | Requires `playsinline`, `viewport-fit=cover`, and visual viewport adjustments for the soft keyboard. |
| Desktop | Chrome / Edge / Firefox | Supported | Fullscreen and native keyboard behavior remain standard. |

## iOS-specific handling

- Add `playsinline` and `webkit-playsinline` behavior for media whenever a video element is used.
- Use `visualViewport` to adjust the app height when the keyboard opens or closes.
- Hide the address bar when the app is launched as a PWA and keep the viewport stable during inline input.
- Keep modal UI anchored to the viewport rather than the static window height.

## Android-specific handling

- Preserve `playsinline` so the browser does not switch to fullscreen when media starts.
- Use `wakeLock` when the browser supports it so the screen stays on during control sessions.
- Collapse/responsive resizing should be handled with `visualViewport` when available.

## Known limitations

- iOS Safari may still keep the address bar visible when not launched as a standalone PWA.
- Some browser engines do not allow programmatic fullscreen without a user gesture.
- Short sessions that lose focus may release `Wake Lock` automatically; the app should re-request it after navigation or focus recovery.

## Validation checklist

- PWA can be added to the home screen on iOS and Android.
- The login and control panels remain visible when the virtual keyboard opens.
- Media does not jump to native fullscreen unexpectedly.
- The app stays awake during active sessions on supported Android browsers.
