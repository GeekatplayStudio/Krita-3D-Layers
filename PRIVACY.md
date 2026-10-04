# Privacy Policy - Geekatplay 3D Layers for Krita

Geekatplay Studio - Vladimir Chopine - https://www.geekatplay.com

Last updated: October 4, 2026

Geekatplay 3D Layers for Krita (the plugin) does not collect, store or send any personal data
to Geekatplay Studio. There are no Geekatplay accounts and no tracking.

## What the plugin sends, and where

The plugin talks only to the 3D services you set up, and only when you use them:

- **When you click Generate:** the pixels of the layer or selection you chose go to the one
  service you picked: Meshy (meshy.ai), Tripo (tripo3d.ai), Hitem3D (hi3d.ai) or your ComfyUI
  server, with the settings for that service (model, quality, and so on).
- **Your API key** for that service is sent with each of its requests, as the service requires.
  Keys are never sent anywhere else.
- **When a job finishes:** the plugin downloads the model and its preview from that service.
- **Test connection** asks the service for your account balance.

Each service handles what you send under its own privacy policy:

- Meshy: https://www.meshy.ai/privacy-policy
- Tripo: https://www.tripo3d.ai/privacy
- Hitem3D: https://docs.hitem3d.ai/en/api/resources/privacy-policy

A ComfyUI server is your own (or one you choose).

## The 3D editor window

The 3D editor runs in a browser window that the plugin opens. It talks only to Krita, through a
private address on your own computer (127.0.0.1) that changes every time. The picture of your
image shown around the model ("Show document") goes only to that window. It is not saved and not
sent anywhere.

## What is stored

On your computer, in your user folder (`%APPDATA%\Geekatplay\3D Layers` on Windows,
`~/Library/Application Support/Geekatplay/3D Layers` on macOS, `~/.local/share/Geekatplay/3D Layers`
on Linux), shared with Geekatplay 3D Layers for Photoshop:

- the model library: the models, their previews, and the image each generated model was made from;
- your API keys (`credentials.json`, readable only by your user on macOS and Linux);
- the plugin's settings, recent jobs, and a log of what it did. The log never contains API keys.

Inside your `.kra` files: each 3D layer's model name, pose and lighting, so it can be edited again.

Nothing of this leaves your computer unless you send it.

## Contact

Questions: https://www.geekatplay.com
