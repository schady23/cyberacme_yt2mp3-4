# Host on Linux Mint on your home network

Run these commands on the Mint server using a normal account with sudo access. This setup uses Gunicorn to serve Flask and systemd to start it after reboot. The app has no login or resource quotas, so keep it on a trusted home network and leave router port forwarding disabled for port 5000.

## Install and clone

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip ffmpeg curl unzip
cd ~
git clone https://github.com/schady23/cyberacme_yt2mp3-4.git
cd cyberacme_yt2mp3-4
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-server.txt
```

Create a fresh Linux virtual environment even if you previously ran the project on Windows. Python 3.10 or newer is required.

Install Deno using its [official installer](https://docs.deno.com/runtime/getting_started/installation/):

```bash
curl -fsSL https://deno.land/install.sh | sh
export PATH="$HOME/.deno/bin:$PATH"
deno --version
ffmpeg -version
ffprobe -version
```

A supported Node.js runtime is an alternative to Deno. The app detects either from PATH; the service example includes the default Deno installation directory. The pip dependency `yt-dlp[default]` includes the companion challenge scripts. See the [yt-dlp runtime guide](https://github.com/yt-dlp/yt-dlp/wiki/ejs).

## Test home-network access

```bash
.venv/bin/gunicorn --workers 1 --worker-class gthread --threads 8 --timeout 120 --bind 0.0.0.0:5000 app:app
```

Keep exactly one worker: job status is stored in memory, and multiple worker processes would not share it. Eight request threads allow concurrent web requests; they do not limit how many conversion jobs can be started. Do not enable auto-reload for the server.

In a second terminal, find the server's home-network IPv4 address:

```bash
hostname -I
```

On a device on the same network, open `http://SERVER_IP:5000`, for example `http://192.168.1.50:5000`. Test a short conversion and download. `0.0.0.0` is a listening address; use the server's actual IP in your browser.

If Mint's firewall is active, allow the port from your home subnet. Check the status and subnet first:

```bash
sudo ufw status
ip -4 route
```

For a home subnet of `192.168.1.0/24`:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 5000 proto tcp
```

Use your actual subnet. If you administer Mint over SSH and choose to enable its firewall, allow your SSH port first to preserve access.

After the conversion test, press Ctrl+C in the first terminal before starting the systemd service, so the port is free.

## Start automatically with systemd

The example assumes the project is at `/home/YOURUSER/cyberacme_yt2mp3-4`. Find your username and actual project path:

```bash
whoami
pwd
```

Copy and edit the service:

```bash
sudo cp deploy/yt2mp3.service /etc/systemd/system/yt2mp3.service
sudo nano /etc/systemd/system/yt2mp3.service
```

Replace every `YOURUSER` with your Mint username. If your project or home directory differs, update `WorkingDirectory`, `ExecStart`, and the directories in `Environment="PATH=..."`. Use absolute paths; systemd does not expand `~` or `$HOME` in these entries. Leave the service running as your normal user, which owns the project and its output directories.

Save with Ctrl+O, Enter, then Ctrl+X. Enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now yt2mp3
sudo systemctl status yt2mp3 --no-pager
```

Look for `active (running)`, then open `http://SERVER_IP:5000` again. The service runs after logout and starts at boot. A DHCP reservation in your router keeps the server address consistent.

## Logs, updates, and storage

Follow live logs with:

```bash
sudo journalctl -u yt2mp3 -f
```

Press Ctrl+C to leave the log view. This does not stop the service.

When no conversions are active, update the application and dependencies:

```bash
cd ~/cyberacme_yt2mp3-4
git pull --ff-only
.venv/bin/python -m pip install --upgrade -r requirements-server.txt
sudo systemctl restart yt2mp3
```

If you changed the installed service file, run `sudo systemctl daemon-reload` before restarting. Adjust `MAX_DURATION_SECONDS` in the installed service if needed: `14400` is four hours; `0` disables that limit. It limits output duration, not download size or job count.

Restarting interrupts active downloads and clears in-memory job status. Completed files stay in `downloads/`; remove old files as needed because there is no automatic expiry. Temporary job directories are cleaned on normal completion or failure, but an abrupt shutdown can leave files in `temp/`. A section retry may download the full source before cutting it, so allow enough free disk space.

If the service fails to start, check the journal, verify all `YOURUSER` placeholders were replaced, and confirm another process is not already using port 5000. If the page works but YouTube fails, update `yt-dlp[default]` and check that Deno or Node is on the service's PATH. Private, region-restricted, or otherwise inaccessible videos may still fail.
