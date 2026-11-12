# Staging on a spare laptop (D-169)

Staging runs on one spare laptop with Ubuntu Server and a single-node k3s. It is **pull-based**:
every night a job on the laptop pulls `main`, builds the images, upgrades the release and tests
it. Nothing ever pushes to the laptop. It is **never a CI runner** and has no inbound webhook.
The nightly run is also a rehearsal of the offline installer (step 7.5).

Follow the steps in order. Commands run on the laptop over SSH unless a step says otherwise.
Names used throughout, change them consistently if you pick others:

| Name | Value in this runbook |
|---|---|
| Laptop hostname | `sx-staging` |
| LAN name of the app | `sx-staging.lan` (or `sx-staging.home.arpa`, the official home-network suffix) |
| Laptop LAN address | `192.168.1.50` (fixed by a DHCP reservation on the router) |
| LAN range | `192.168.1.0/24` |
| Your admin user | `haider` |
| The job's user | `sxstaging` |
| The job's checkout | `/srv/supportx-staging/checkout` |
| Kubernetes namespace and Helm release | `supportx` and `supportx` |

The laptop is assumed to be x86-64 (amd64). On an ARM laptop, use the `arm64` downloads.

Repo files this runbook uses:

- `deploy/staging/nightly.sh`: the nightly job.
- `deploy/staging/supportx-staging.service` and `.timer`: its systemd units.
- `deploy/staging/staging.env.example`: the job's settings.
- `deploy/staging/traefik-config.yaml`: k3s's Traefik, HTTPS on the LAN only.
- `deploy/helm/supportx/values-staging.yaml`: the staging overlay on `values-single-node.yaml`.

---

## 1. Prepare the OS

**1.1 Install Ubuntu Server LTS** (26.04 LTS, or 24.04 LTS). In the installer:

- Create your admin user (`haider`). It gets `sudo`. Never work as root.
- Tick **Install OpenSSH server**.
- Storage: use the largest disk, with LVM (the default). See 1.6.
- Hostname: `sx-staging`.
- Skip every optional snap (no Docker snap: Docker comes from apt in step 2).

**1.2 Update and set the hostname.**

```bash
sudo apt update && sudo apt full-upgrade -y
sudo hostnamectl set-hostname sx-staging
```

On the router: give the laptop a fixed address (DHCP reservation, `192.168.1.50`). Turn off any
port forwarding and UPnP for it.

**1.3 SSH with keys only.** From your Mac: `ssh-copy-id haider@192.168.1.50`. Check that a key
login works, then on the laptop:

```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' \
  | sudo tee /etc/ssh/sshd_config.d/10-sx-staging.conf
sudo systemctl reload ssh
```

**1.4 Unattended security upgrades**, with a reboot at 06:00 when one is needed (after the
nightly run, which starts at 03:00):

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades      # answer Yes
printf 'Unattended-Upgrade::Automatic-Reboot "true";\nUnattended-Upgrade::Automatic-Reboot-Time "06:00";\n' \
  | sudo tee /etc/apt/apt.conf.d/52sx-staging
```

**1.5 Time zone and time sync.**

```bash
sudo timedatectl set-timezone Asia/Karachi
timedatectl          # "System clock synchronized: yes"
```

Ubuntu syncs time out of the box (chrony on 26.04, systemd-timesyncd on 24.04). The nightly
timer runs at 03:00 in this time zone.

**1.6 Disk layout.** k3s keeps its volumes (database, NATS, files) under its data directory,
and Docker keeps build layers under its own. Both must be on the largest disk.

```bash
lsblk
df -h /
```

- **One disk:** Ubuntu's installer often gives the root volume only part of the disk. Give it
  the rest:
  ```bash
  sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
  ```
- **Two disks, the second one larger and empty:** mount it at `/data`. `mkfs` wipes the disk:
  check the device name with `lsblk` first.
  ```bash
  sudo mkfs.ext4 -L sxdata /dev/sdb                      # CHECK the device name
  sudo mkdir /data
  echo 'LABEL=sxdata /data ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
  sudo mount /data && df -h /data
  ```
  Then use `data-dir: /data/k3s` in step 3.1 and `"data-root": "/data/docker"` in step 2.1.

**1.7 Memory and swap.** 16 GB of memory is the minimum (`values-staging.yaml` is sized for
it); 32 GB is comfortable. Kubernetes expects swap off. Ubuntu Server makes a swap file, so
turn it off:

```bash
sudo swapoff -a
sudo sed -i.bak '/^\/swap.img/ s/^/#/' /etc/fstab
free -h              # Swap: 0B
```

**1.8 Keep running with the lid closed.**

```bash
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' \
  | sudo tee /etc/systemd/logind.conf.d/lid.conf
sudo systemctl restart systemd-logind
```

Leave it on mains power. If the firmware has "power on after power loss", turn it on.

**1.9 Firewall (ufw): SSH and HTTPS from the LAN only.**

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp    # SSH, LAN only
sudo ufw allow from 192.168.1.0/24 to any port 443 proto tcp   # the app (HTTPS), LAN only
sudo ufw allow from 10.42.0.0/16                                # k3s pods, inside the laptop
sudo ufw allow from 10.43.0.0/16                                # k3s services, inside the laptop
sudo ufw enable
sudo ufw status verbose
```

What this means:

- **No inbound port is open beyond SSH and HTTPS, and both only from the LAN.** Nothing is
  reachable from the internet. The Kubernetes API (6443) is not opened: use `kubectl` on the
  laptop, over SSH.
- The two `10.42`/`10.43` rules are k3s's own pod and service networks. They are traffic inside
  the laptop, not from outside.
- k3s forwards port 443 to Traefik with its own iptables rules, which ufw's rules do not see.
  So the LAN-only limit for 443 is also set in Traefik's load balancer (step 3.2), and port 80
  is not exposed at all.
- The real guard against the internet is the router: no port forwarding to the laptop, no UPnP.
- **No CI runner and no inbound webhook is installed. The laptop only pulls.**

Check from another machine on the LAN, once the app runs (step 6): `nc -vz 192.168.1.50 443`
connects, `nc -vz 192.168.1.50 80` and `nc -vz 192.168.1.50 6443` do not.

---

## 2. Tools

**Why the laptop builds its own images.** `make images` builds the three INTERNAL/DEV images
(`supportx-backend`, `supportx-worker`, `supportx-web`). They must only ever go to private
registries (D-038), and staging has none. So the laptop builds them from the pulled source and
imports them straight into k3s's container store. It is what `make deploy-dev` does for k3d
(`k3d image import`). On plain k3s the import is
`docker save ... | sudo k3s ctr images import -`. The chart then runs them with
`pullPolicy: Never` (`values-staging.yaml`), so no SupportX image is ever pulled.

`make images` first runs `make generated` (labels, OpenAPI, API types, D-127). That needs the
backend's uv environment and the frontend's pnpm packages. So the laptop needs uv, Node and
pnpm as well as Docker.

**2.1 Packages: git, make, Docker (with BuildKit), and the small tools the scripts use.**

```bash
sudo apt install -y git make curl jq openssl ca-certificates python3 xz-utils docker.io docker-buildx
```

`deploy/scripts/secrets.sh` uses `openssl` and `python3`. With a second disk (1.6), point
Docker at it **before** the first build:

```bash
echo '{"data-root": "/data/docker"}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

**2.2 Helm v4.3.1** (the version CI pins: `azure/setup-helm` in `.github/workflows/ci.yml`).

```bash
cd /tmp
curl -fsSLO https://get.helm.sh/helm-v4.3.1-linux-amd64.tar.gz
curl -fsSLO https://get.helm.sh/helm-v4.3.1-linux-amd64.tar.gz.sha256sum
sha256sum -c helm-v4.3.1-linux-amd64.tar.gz.sha256sum          # OK
tar -xzf helm-v4.3.1-linux-amd64.tar.gz
sudo install -m 0755 linux-amd64/helm /usr/local/bin/helm
helm version                                                    # v4.3.1
```

**2.3 kubectl** comes with k3s (step 3): the installer links `/usr/local/bin/kubectl` to k3s,
so its version always matches the cluster's.

**2.4 uv 0.12.19** (pinned in `.github/actions/setup-backend/action.yml`). uv installs Python
3.12 itself, from `backend/.python-version`. Never the system `python3` for the backend.

```bash
cd /tmp
curl -fsSLO https://github.com/astral-sh/uv/releases/download/0.12.19/uv-x86_64-unknown-linux-gnu.tar.gz
curl -fsSLO https://github.com/astral-sh/uv/releases/download/0.12.19/uv-x86_64-unknown-linux-gnu.tar.gz.sha256
sha256sum -c uv-x86_64-unknown-linux-gnu.tar.gz.sha256
tar -xzf uv-x86_64-unknown-linux-gnu.tar.gz
sudo install -m 0755 uv-x86_64-unknown-linux-gnu/uv uv-x86_64-unknown-linux-gnu/uvx /usr/local/bin/
uv --version                                                    # uv 0.12.19
```

**2.5 Node 24.22.1 and pnpm** (`.nvmrc`; pnpm 12.15.0 from `packageManager` in
`frontend/package.json`, through corepack).

```bash
cd /tmp
curl -fsSLO https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.xz
curl -fsSLO https://nodejs.org/dist/v24.22.1/SHASUMS256.txt
grep ' node-v24.22.1-linux-x64.tar.xz$' SHASUMS256.txt | sha256sum -c -
sudo mkdir -p /opt/node
sudo tar -xJf node-v24.22.1-linux-x64.tar.xz -C /opt/node --strip-components=1
sudo /opt/node/bin/corepack enable
echo 'export PATH=/opt/node/bin:$PATH' | sudo tee /etc/profile.d/node.sh
```

Log out and in again, then `node --version` shows v24.22.1.

**2.6 The job's user and its dedicated checkout.** The nightly job runs as its own user,
`sxstaging`, in its own clone. It runs `git reset --hard` there, so it must **never** be
anyone's working copy. Nobody edits files in it.

```bash
sudo adduser --system --group --home /home/sxstaging --shell /bin/bash sxstaging
sudo usermod -aG docker sxstaging
sudo install -d -o sxstaging -g sxstaging -m 0755 /srv/supportx-staging
```

Membership of the `docker` group is as powerful as root. That is acceptable here because the
laptop does nothing else.

Read-only access to GitHub with a deploy key (outbound only):

```bash
sudo -iu sxstaging ssh-keygen -t ed25519 -N '' -C 'sx-staging read-only' -f /home/sxstaging/.ssh/id_ed25519
sudo cat /home/sxstaging/.ssh/id_ed25519.pub
```

On GitHub: the repo › Settings › Deploy keys › Add deploy key. Paste the public key. Leave
**Allow write access** off. Then clone, and mark the clone as the job's own:

```bash
sudo -iu sxstaging git clone git@github.com:Extravis-islamabad/supportx-v2.git /srv/supportx-staging/checkout
sudo -iu sxstaging touch /srv/supportx-staging/checkout/.git/supportx-staging-dedicated
```

At the first connection ssh asks to trust GitHub's host key. Compare the fingerprint with the
one GitHub publishes ("GitHub's SSH key fingerprints" in GitHub's docs) before typing `yes`.
`nightly.sh` refuses to run in a checkout without the `.git/supportx-staging-dedicated` marker.

**2.7 Let the job import images into k3s,** and nothing else as root:

```bash
echo 'sxstaging ALL=(root) NOPASSWD: /usr/local/bin/k3s ctr images import -' \
  | sudo tee /etc/sudoers.d/supportx-staging
sudo chmod 0440 /etc/sudoers.d/supportx-staging
sudo visudo -cf /etc/sudoers.d/supportx-staging                # parsed OK
```

---

## 3. k3s, single node

The repo pins k3s **v1.36.5+k3s1** (`deploy/k3d/cluster.yaml`, D-038), the same as CI and the
on-prem appliance.

**3.1 k3s settings, before installing.** Secrets encrypted at rest, as on the appliance:

```bash
sudo mkdir -p /etc/rancher/k3s
printf 'secrets-encryption: true\nwrite-kubeconfig-mode: "0600"\nnode-name: sx-staging\n' \
  | sudo tee /etc/rancher/k3s/config.yaml
# With a second disk (1.6) only:
# echo 'data-dir: /data/k3s' | sudo tee -a /etc/rancher/k3s/config.yaml
```

**3.2 Traefik for staging.** k3s bundles Traefik. `deploy/staging/traefik-config.yaml` turns on
its Gateway API provider (as `deploy/k3d/traefik-config.yaml` does for k3d), keeps realtime
connections open on HTTPS, does not expose port 80, and accepts only the LAN range. Put it in
k3s's manifests folder before the first start, then **change the LAN range in it** to yours:

```bash
sudo mkdir -p /var/lib/rancher/k3s/server/manifests      # with data-dir: /data/k3s/server/manifests
sudo cp /srv/supportx-staging/checkout/deploy/staging/traefik-config.yaml \
  /var/lib/rancher/k3s/server/manifests/traefik-config.yaml
sudo nano /var/lib/rancher/k3s/server/manifests/traefik-config.yaml   # the CHANGE line
```

**3.3 Install the pinned k3s.** Download the install script, then run it with the version
pinned:

```bash
curl -sfL https://get.k3s.io -o /tmp/k3s-install.sh
sudo INSTALL_K3S_VERSION='v1.36.5+k3s1' sh /tmp/k3s-install.sh
sudo k3s kubectl get nodes          # sx-staging   Ready   ...   v1.36.5+k3s1
```

**3.4 kubeconfig** for you and for the job's user. It is cluster-admin: it never leaves the
laptop.

```bash
mkdir -p ~/.kube
sudo install -o "$USER" -g "$USER" -m 0600 /etc/rancher/k3s/k3s.yaml ~/.kube/config
echo 'export KUBECONFIG=$HOME/.kube/config' >> ~/.bashrc && . ~/.bashrc
sudo install -d -o sxstaging -g sxstaging -m 0700 /home/sxstaging/.kube
sudo install -o sxstaging -g sxstaging -m 0600 /etc/rancher/k3s/k3s.yaml /home/sxstaging/.kube/config
echo 'export KUBECONFIG=$HOME/.kube/config' | sudo -u sxstaging tee -a /home/sxstaging/.bashrc
kubectl get nodes
```

**3.5 Wait for Traefik,** then check that the Gateway API is on (as `deploy/k3d/up.sh` does):

```bash
kubectl -n kube-system rollout status deploy/traefik --timeout=300s
kubectl get gatewayclass traefik
kubectl -n kube-system get svc traefik      # PORT(S) shows 443, not 80
```

**3.6 Cluster prerequisites.** `deploy/k3d/prereqs.sh` installs them with Helm into whatever
cluster the kubeconfig points at, so it works on k3s as it is. It installs the CloudNativePG
operator (pinned chart 0.29.1) and checks the Traefik GatewayClass. cert-manager and the Barman
Cloud backup plugin come only with `BACKUP_PLUGIN=1` (the optional backup rehearsal, step 9.4).

```bash
sudo -iu sxstaging bash -c 'cd /srv/supportx-staging/checkout && bash deploy/k3d/prereqs.sh'
```

It is idempotent: run it again whenever its pinned versions change on `main`.

---

## 4. Profile, LAN name and TLS

**4.1 The profile.** Staging uses `values-single-node.yaml` (the appliance profile: production
mode, HTTPS on Traefik's websecure listener, bundled Temporal) plus a small overlay,
`deploy/helm/supportx/values-staging.yaml`. The overlay sets:

- `publicUrl: https://sx-staging.lan` and `routing.hostnames`;
- `routing.gateway.tlsSecret: supportx-tls` (made in 5.2);
- the locally built images, `pullPolicy: Never`;
- demo data: `app.seedDevData: true` and `keycloak.realmImport: dev` (the Demo and Other
  companies and the dev realm's demo users; their passwords are in `docs/dev-setup.md`);
- laptop sizes for PostgreSQL, NATS, SeaweedFS, Keycloak, ClamAV and Temporal.

`values-dev.yaml` is **not** used: it is for k3d only (plain http, the Keycloak admin API
public, a database port on the host).

Volume sizes and Temporal's shard count are fixed at the first install. Change them in the
overlay before step 6, not after.

**4.2 A different LAN name** goes in a local file on the laptop, never in the repo file. The
nightly job adds it when it exists:

```bash
sudo mkdir -p /etc/supportx-staging
sudo tee /etc/supportx-staging/values-local.yaml <<'EOF'
publicUrl: https://staging.home.arpa
routing:
  hostnames: [staging.home.arpa]
EOF
```

Skip this if you keep `sx-staging.lan`.

**4.3 Make the name resolve.** On the router's DNS, add `sx-staging.lan → 192.168.1.50`. If
the router can't, add the line to `/etc/hosts` on each machine that uses staging. Add it on
the laptop too, for the job's smoke check:

```bash
echo '192.168.1.50 sx-staging.lan' | sudo tee -a /etc/hosts
```

**4.4 TLS from the laptop's own small CA.** A self-signed CA, made once with `openssl`. The CA
key never leaves the laptop. The CA certificate (`ca.crt`) is public: install it on the machines
that open staging.

```bash
sudo install -d -m 0700 /etc/supportx-staging/tls
sudo -i
cd /etc/supportx-staging/tls
openssl req -x509 -new -nodes -newkey rsa:3072 -sha256 -days 1825 \
  -keyout ca.key -out ca.crt -subj '/CN=SupportX staging CA (sx-staging)' \
  -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign'
openssl req -new -nodes -newkey rsa:2048 -keyout tls.key -out tls.csr -subj '/CN=sx-staging.lan'
printf 'subjectAltName=DNS:sx-staging.lan\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' > tls.ext
openssl x509 -req -in tls.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 -sha256 \
  -extfile tls.ext -out tls.crt
install -m 0644 ca.crt /etc/supportx-staging/ca.crt
exit
```

On your Mac: copy `ca.crt` across and trust it.

```bash
scp haider@192.168.1.50:/etc/supportx-staging/ca.crt ~/Downloads/sx-staging-ca.crt
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/Downloads/sx-staging-ca.crt
```

The server certificate lasts a year. To renew: repeat the `tls.csr`, `tls.ext` and `tls.crt`
lines, then step 5.2 with `--dry-run=client -o yaml | kubectl apply -f -` added. cert-manager
with a CA issuer would renew it by itself; it is approved (D-037) but not needed for one laptop.

**4.5 GlitchTip (D-167, when it lands).** Placeholder. D-167 approved self-hosted GlitchTip
for error tracking, but it is not built yet: the chart has no values for it **(not yet in the
repo)**. When it lands, add its values to `values-staging.yaml` here. Until then errors are in
the pod logs (step 8).

---

## 5. Secrets

**5.1 The chart's Secrets.** `deploy/scripts/secrets.sh` creates the namespace if missing and
the `supportx-app` and `supportx-db-keycloak` Secrets with random values. It never overwrites a
value: on later runs it only adds keys that newer versions need. The nightly job re-runs it
before every upgrade.

```bash
sudo -iu sxstaging bash -c 'cd /srv/supportx-staging/checkout && bash deploy/scripts/secrets.sh supportx'
```

**5.2 The TLS Secret,** from 4.4:

```bash
sudo k3s kubectl -n supportx create secret tls supportx-tls \
  --cert=/etc/supportx-staging/tls/tls.crt --key=/etc/supportx-staging/tls/tls.key
```

**Where the secrets live:** in k3s's own datastore on the laptop (under
`/var/lib/rancher/k3s/server/`), encrypted at rest (`secrets-encryption`, 3.1). The CA key is
in `/etc/supportx-staging/tls/`, readable by root only. They are **never copied off the laptop,
never committed, never pasted into chat, tickets or screenshots.** Read one only on the laptop
when you need it, e.g. Keycloak's admin password:

```bash
kubectl -n supportx get secret supportx-app -o jsonpath='{.data.keycloak-admin-password}' | base64 -d; echo
```

---

## 6. First install (by hand, once)

The nightly job only upgrades. The first install is done by hand, so a failure can be looked at
before anything retries. Run it as the job's user, in its checkout:

```bash
sudo -iu sxstaging
cd /srv/supportx-staging/checkout
(cd backend && uv sync --frozen)
(cd frontend && pnpm install --frozen-lockfile)
TAG="$(git rev-parse --short=12 HEAD)"
make images IMAGE_TAG="$TAG"                         # runs make generated first; ~15-30 min the first time
docker save "supportx-backend:$TAG" "supportx-worker:$TAG" "supportx-web:$TAG" \
  | sudo -n /usr/local/bin/k3s ctr images import -
make chart-deps                                      # NATS and Valkey charts from Chart.lock
bash deploy/scripts/secrets.sh supportx              # adds nothing if 5.1 already ran
helm install supportx deploy/helm/supportx -n supportx \
  -f deploy/helm/supportx/values-single-node.yaml \
  -f deploy/helm/supportx/values-staging.yaml \
  --set-string images.backend.tag="$TAG" \
  --set-string images.worker.tag="$TAG" \
  --set-string images.web.tag="$TAG" \
  --wait --timeout 15m
helm test supportx -n supportx --logs --filter '!name=supportx-valkey-test-auth-existing'
curl -fsS --cacert /etc/supportx-staging/ca.crt https://sx-staging.lan/api/v1/ready; echo
exit
```

- With `/etc/supportx-staging/values-local.yaml` (4.2), add
  `-f /etc/supportx-staging/values-local.yaml` after the staging file.
- The `helm test` filter is the Makefile's `HELM_TEST`: the upstream Valkey auth test is left
  out because our NetworkPolicy refuses its connection.
- If the install fails, look at step 8, fix the cause, then run the same command with
  `helm upgrade` in place of `helm install`. Do not uninstall: that deletes the database cluster.

Open `https://sx-staging.lan` (console) and `https://sx-staging.lan/portal/` (portal). Sign in
with a demo user from `docs/dev-setup.md`, e.g. `admin@demo.test`.

---

## 7. The nightly job

**7.1 What it does.** `deploy/staging/nightly.sh` runs at 03:00 (plus up to 15 minutes at
random) as `sxstaging`:

1. Refuses to run unless the checkout has the `.git/supportx-staging-dedicated` marker (2.6).
2. `git fetch` and `git reset --hard origin/main` in the dedicated checkout, then `git clean -fd`
   (ignored caches such as `.venv` and `node_modules` stay).
3. `uv sync --frozen` and `pnpm install --frozen-lockfile`.
4. `make generated`.
5. `make images IMAGE_TAG=<commit>`: images tagged by commit, so `helm rollback` really returns
   to the older images.
6. Imports the images into k3s (`k3s ctr images import`).
7. `make chart-deps`, then `deploy/scripts/secrets.sh supportx` (adds missing keys only).
8. `helm upgrade --install ... --rollback-on-failure --wait --timeout 15m` with
   `values-single-node.yaml`, `values-staging.yaml` and, if present, `values-local.yaml`.
   It refuses if the release does not exist yet (step 6 is by hand).
9. `helm test` (the same filter as step 6).
10. Smoke check: `curl` of `<PUBLIC_URL>/api/v1/ready` through Traefik, with the staging CA.
11. `make e2e-smoke` against the laptop, **only once that target exists**: the browser smoke
    suite is **(not yet in the repo)**, so today this step logs "skipped". Optional until then.
12. Tidies up: removes Docker's copies of older SupportX images (k3s keeps its own copies for
    rollback), prunes build cache older than 7 days, deletes job logs older than 14 days.

**7.2 Why `--rollback-on-failure`.** It is Helm 4's name for `--atomic` (Helm 4 still accepts
`--atomic` but marks it deprecated). Without it, a failed `helm upgrade --wait` leaves the
release marked *failed* with the broken pods half rolled out. With it, Helm rolls the release
straight back to the last good revision, so last night's working staging keeps running.
Note what it does **not** cover:

- The migrate Job may already have applied new migrations. They stay: the schema is
  forward-only (step 9).
- If `helm test` or the smoke check fails *after* a successful upgrade, nothing is rolled back.
  The run is marked failed and you decide (step 9).

**7.3 Install it.**

```bash
sudo cp /srv/supportx-staging/checkout/deploy/staging/staging.env.example /etc/supportx-staging/staging.env
sudo nano /etc/supportx-staging/staging.env          # PUBLIC_URL, if not https://sx-staging.lan
sudo cp /srv/supportx-staging/checkout/deploy/staging/supportx-staging.service \
        /srv/supportx-staging/checkout/deploy/staging/supportx-staging.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start --no-block supportx-staging.service    # one run now, to check it
journalctl -u supportx-staging.service -f                    # Ctrl+C to stop watching
cat /var/lib/supportx-staging/last-run                       # result=ok
sudo systemctl enable --now supportx-staging.timer
systemctl list-timers supportx-staging.timer                 # NEXT: tomorrow 03:00-03:15
```

The unit files and `staging.env` are copies. A change to them on `main` does not reach the
laptop by itself: copy them again and run `sudo systemctl daemon-reload`. That is on purpose:
the job never changes its own setup. A change to `nightly.sh` itself takes effect the night
after it is pulled.

**7.4 The unit files,** as in the repo:

`deploy/staging/supportx-staging.service`

```ini
# The staging laptop's nightly run (D-169; docs/runbooks/staging-laptop.md, step 7).
# Install: sudo cp deploy/staging/supportx-staging.{service,timer} /etc/systemd/system/
# Started by supportx-staging.timer; start one run by hand with
#   sudo systemctl start supportx-staging.service
[Unit]
Description=SupportX staging: pull main, build, upgrade and test (D-169)
Wants=network-online.target
After=network-online.target docker.service k3s.service
Requires=docker.service k3s.service

[Service]
Type=oneshot
User=sxstaging
Group=sxstaging
# Creates /var/log/supportx-staging and /var/lib/supportx-staging, owned by sxstaging.
LogsDirectory=supportx-staging
StateDirectory=supportx-staging
Environment=SUPPORTX_STAGING_CONFIG=/etc/supportx-staging/staging.env
Environment=PATH=/opt/node/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/srv/supportx-staging/checkout/deploy/staging/nightly.sh
# A build plus a 15 minute upgrade fits easily; a run stuck longer is stopped and fails.
TimeoutStartSec=2h
# Builds are heavy: let anything interactive on the laptop go first.
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
```

`deploy/staging/supportx-staging.timer`

```ini
# Nightly at 03:00 local time, plus up to 15 minutes at random (D-169; runbook step 7).
# Persistent: a run missed while the laptop was off starts soon after it comes back.
[Unit]
Description=SupportX staging: nightly pull, build, upgrade and test

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=15min
Unit=supportx-staging.service

[Install]
WantedBy=timers.target
```

**7.5 How the run rehearses the offline installer.** An air-gapped install runs the same
sequence: images loaded into k3s's container store from local files rather than pulled, the
chart's dependencies from local tarballs (`make chart-deps` reuses the ones in `charts/`),
`secrets.sh` on the cluster, `helm upgrade --install --wait`, `helm test`. No SupportX image
is pulled from anywhere.

It is not yet a true offline rehearsal. Still reached over the internet:

- `git pull` of the source, and the build's own downloads: Python and npm packages, and the
  Dockerfiles' base images (Python, uv, Node, nginx);
- the third-party images k3s pulls at install: Keycloak, the CloudNativePG PostgreSQL image,
  NATS, Valkey, Centrifugo, SeaweedFS, ClamAV, Temporal;
- the Helm repos for `prereqs.sh` and the chart's dependencies (until they are cached);
- ClamAV's signature updates (`deploy/scripts/clamav-signatures.sh` loads an offline bundle);
- k3s itself (the installer downloads it).

Missing for a true offline rehearsal **(not yet in the repo)**: an image bundle holding every
image (SupportX and third-party), or a Zot mirror (D-038) with `images.registry` pointed at it;
k3s's air-gap images and install; the signed release bundle and the installer itself (WP-014c).
When those exist, the job should install from the bundle instead of building.

---

## 8. Logs

| What | Command |
|---|---|
| The job, live or past | `journalctl -u supportx-staging.service -n 200 --no-pager` (`-f` to follow, `--since today`) |
| The job's dated logs (14 days) | `ls -lt /var/log/supportx-staging/` then `less /var/log/supportx-staging/nightly-<date>.log` |
| Last run's result | `cat /var/lib/supportx-staging/last-run` (`result`, failed `step`, `commit`, `log`); last good run: `last-success` |
| The timer | `systemctl list-timers supportx-staging.timer` |
| Pods | `kubectl -n supportx get pods`; a stuck one: `kubectl -n supportx describe pod <pod>` |
| API and workers | `kubectl -n supportx logs deploy/supportx-api --tail=200` (also `supportx-relay`, `supportx-consumers`, `supportx-fanout`, `supportx-sla-timers`, `supportx-workflow-timers`, `supportx-web`, `supportx-keycloak`) |
| A crashed container's last run | `kubectl -n supportx logs <pod> --previous` |
| Migrations | `kubectl -n supportx logs job/supportx-migrate-<revision>` (the revision from `helm history`) |
| Releases | `helm history supportx -n supportx`; one revision's values: `helm get values supportx -n supportx --revision <rev>` |
| k3s itself | `journalctl -u k3s -n 200 --no-pager` |
| Images k3s holds | `sudo k3s crictl images \| grep supportx` |

The production profile logs JSON, one line per event. More pointers: `docs/deployment.md`,
Troubleshooting.

---

## 9. Rollback

**9.1 Hold the nightly job first,** or tonight's run upgrades to `main` again:

```bash
sudo systemctl stop supportx-staging.timer
systemctl is-active supportx-staging.service       # "inactive": no run in progress
```

**9.2 Roll back.**

```bash
helm history supportx -n supportx                  # pick the last good REVISION
helm get values supportx -n supportx --revision <rev> | grep -A1 'backend:'   # its image tag
sudo k3s crictl images | grep supportx             # that tag must still be there
helm rollback supportx <rev> -n supportx --wait --timeout 15m
helm test supportx -n supportx --logs --filter '!name=supportx-valkey-test-auth-existing'
```

If k3s has already removed that revision's images (it does under disk pressure), build them
again: as `sxstaging`, in the checkout, `git checkout <commit>`, then `make images IMAGE_TAG=<commit>`
and the import line from step 6. The next nightly run puts the checkout back on `main`.

When `main` is fixed, start the timer again: `sudo systemctl start supportx-staging.timer`.

**9.3 What a rollback does not undo.**

- **Database migrations.** They are forward-only (expand/contract, architecture.md §14.3).
  `helm rollback` moves only the images and settings. The older app version then runs against
  the newer schema, which the expand/contract rule allows.
- Data written since the upgrade, NATS streams, the Keycloak realm, files in SeaweedFS, and
  the Secrets (`secrets.sh` only adds keys).

**Restore a backup instead** when the data itself is wrong (a bad data migration, a bad
import), or when the older version cannot run on the newer schema (a migration broke the
expand/contract rule; that is a bug to report). On staging the simplest fix may be to start
over with fresh demo data. That deletes the release's volumes, so it is a deliberate choice:
decide it yourself, never as a routine step.

**9.4 Backups on one laptop are for rehearsal only.** The backups and the database share one
disk, so losing the laptop loses both. To rehearse backup and restore anyway:

```bash
sudo -iu sxstaging bash -c 'cd /srv/supportx-staging/checkout && BACKUP_PLUGIN=1 bash deploy/k3d/prereqs.sh'
printf 'postgresql:\n  cnpg:\n    backup:\n      enabled: true\n' | sudo tee -a /etc/supportx-staging/values-local.yaml
```

(If `values-local.yaml` already has a `postgresql:` section, add `backup.enabled: true` inside it
instead of appending.) The next run backs up to the release's own SeaweedFS (the chart warns that this is in-cluster).
Restore by following `docs/runbooks/restore.md`.

---

## 10. Updating the laptop itself

- **Security updates** install themselves (1.4) and reboot at 06:00 when needed.
  `ls /var/run/reboot-required` shows a pending one.
- **Other packages:** once a month, outside 03:00 to 05:00:
  `sudo apt update && sudo apt full-upgrade -y`, then reboot if asked.
- **After any reboot** k3s and Docker start by themselves and the pods come back within a few
  minutes. A nightly run missed while the laptop was off starts soon after boot (`Persistent`).
  Check: `kubectl -n supportx get pods`.
- **k3s stays pinned.** Upgrade it only when the repo's pin changes (`rancher/k3s:` in
  `deploy/k3d/cluster.yaml`), one minor version at a time:
  ```bash
  sudo systemctl stop supportx-staging.timer
  systemctl is-active supportx-staging.service                  # inactive
  curl -sfL https://get.k3s.io -o /tmp/k3s-install.sh
  sudo INSTALL_K3S_VERSION='<new pin, e.g. v1.37.x+k3s1>' sh /tmp/k3s-install.sh
  kubectl get nodes                                             # the new version, Ready
  kubectl -n supportx get pods                                  # all back
  helm test supportx -n supportx --logs --filter '!name=supportx-valkey-test-auth-existing'
  sudo systemctl start supportx-staging.timer
  ```
  The installer keeps `/etc/rancher/k3s/config.yaml` and the Traefik file. Re-run
  `deploy/k3d/prereqs.sh` (3.6) when its pinned versions change.
- **Helm, uv, Node:** keep them at the repo's pins. Check once a month in the checkout:
  ```bash
  cd /srv/supportx-staging/checkout
  grep -h -A2 'setup-helm@' .github/workflows/ci.yml | grep version   # Helm
  grep -A1 'setup-uv@' .github/actions/setup-backend/action.yml       # uv
  cat .nvmrc                                                            # Node
  grep -o 'rancher/k3s:[^ ]*' deploy/k3d/cluster.yaml                  # k3s
  ```
  A new pin means repeating that tool's part of step 2.

---

## 11. What this staging is NOT

- **Not a CI runner.** No GitHub Actions runner, no inbound webhook, no deploy pushed to it.
  It only pulls.
- **Not reachable from the internet.** SSH and HTTPS from the LAN only (1.9).
- **Not production data.** Only the seeded demo data: the Demo and Other companies and the dev
  realm's users (`app.seedDevData`, `keycloak.realmImport: dev`). The Showcase Company seed
  (`make showcase-seed`, D-124) runs only against the local Compose stack today; seeding it
  into a cluster is **(not yet in the repo)**.
- **Never given customer data**, not even "just to try something".
- **No mail leaves it:** `mail.smtpHost` is empty, so SupportX sends no e-mail (invitations and
  password e-mails are not sent).
- **Not production-grade:** INTERNAL/DEV images (D-038), one node, backups on the same disk.

---

## Not yet in the repo

Steps above that wait for work still to come:

| Gap | Where it matters |
|---|---|
| GlitchTip error tracking (D-167 approved, not built) | 4.5 |
| A browser smoke suite (`make e2e-smoke`) | 7.1, step 11 |
| An image bundle or Zot mirror, k3s air-gap install, signed release bundle and installer (D-038, WP-014c) | 7.5 |
| Seeding the Showcase Company into a cluster | 11 |
