#!/usr/bin/env bash
# Score OmniDocBench runs (results/<key>/) on a big Azure CPU VM instead of the Mac.
#
#   bash azure/score.sh omni_plain omni_mask              # create/start VM, score, pull metrics, deallocate
#   AZ_SIZE=Standard_D96as_v5 AZ_REGION=eastus2 bash azure/score.sh omni_mask
#   AZ_KEEP=1 ...    leave the VM running at the end
#   OMNI_GT=data/omnidocbench/<subset>.json ...   score against a subset of the ground truth
#
# The VM is deallocated (not deleted) at the end: compute billing stops, only the small OS disk is billed,
# and the next run starts in ~1 min with the eval env already installed.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
RG=${AZ_RG:-docengine-rg}
VM=${AZ_VM:-docengine-score}
REGION=${AZ_REGION:-eastus2}
SIZE=${AZ_SIZE:-Standard_F64s_v2}
KEY=${AZ_SSH_KEY:-~/.ssh/docengine_azure}
USER_=azureuser
[ $# -ge 1 ] || { echo "usage: $0 <result_key>..."; exit 1; }
[ -f $KEY ] || ssh-keygen -t ed25519 -N "" -f $KEY -C docengine-azure >/dev/null

if ! az vm show -g $RG -n $VM >/dev/null 2>&1; then
  az group create -n $RG -l $REGION -o none
  az vm create -g $RG -n $VM -l $REGION --size $SIZE --image Ubuntu2204 --admin-username $USER_ \
    --ssh-key-values $KEY.pub --public-ip-sku Standard --os-disk-size-gb 64 --nsg-rule SSH -o none
  # SSH from this machine's current IP only.
  MYIP=$(curl -s https://api.ipify.org)
  az network nsg rule update -g $RG --nsg-name ${VM}NSG -n default-allow-ssh --source-address-prefixes "$MYIP/32" -o none
else
  CUR=$(az vm show -g $RG -n $VM --query hardwareProfile.vmSize -o tsv)
  if [ "$CUR" != "$SIZE" ]; then
    az vm deallocate -g $RG -n $VM -o none; az vm resize -g $RG -n $VM --size $SIZE -o none
  fi
  MYIP=$(curl -s https://api.ipify.org)
  az network nsg rule update -g $RG --nsg-name ${VM}NSG -n default-allow-ssh --source-address-prefixes "$MYIP/32" -o none
  az vm start -g $RG -n $VM -o none
fi
IP=$(az vm show -d -g $RG -n $VM --query publicIps -o tsv)
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ServerAliveInterval=30 $USER_@$IP"
RSYNC="rsync -az --delete -e \"ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR\""
cleanup() {
  if [ -z "${AZ_KEEP:-}" ]; then echo "deallocating $VM"; az vm deallocate -g $RG -n $VM -o none --no-wait; fi
}
trap cleanup EXIT
for i in $(seq 30); do $SSH true 2>/dev/null && break; sleep 10; done
echo "VM $VM ($SIZE) at $IP, $($SSH nproc) vCPUs"

# Code + ground truth + predictions (markdown only).
$SSH "mkdir -p docengine/vendor docengine/data/omnidocbench docengine/bench docengine/results"
eval $RSYNC --exclude result/ --exclude .git vendor/OmniDocBench/ $USER_@$IP:docengine/vendor/OmniDocBench/
eval $RSYNC --include "'*.json'" --exclude "'*'" data/omnidocbench/ $USER_@$IP:docengine/data/omnidocbench/
eval $RSYNC bench/omni/ $USER_@$IP:docengine/bench/omni/
for k in "$@"; do
  eval $RSYNC --include "'*.md'" --exclude "'_*'" results/$k/ $USER_@$IP:docengine/results/$k/
done

# One-time env setup (kept on the disk between runs).
$SSH 'set -e; cd docengine; if [ ! -x .venv-omni/bin/python ]; then
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  export PATH=$HOME/.local/bin:$PATH
  uv venv -q -p 3.10 .venv-omni && uv pip install -q -p .venv-omni/bin/python -e vendor/OmniDocBench
fi'

for k in "$@"; do
  t0=$(date +%s)
  $SSH "cd docengine && mkdir -p vendor/OmniDocBench/result && rm -f results/$k/_omni_metrics.json && \
        OMNI_GT=${OMNI_GT:-} OMNI_PAGE_PROCS=1 OMNI_WORKERS=\$(( \$(nproc) - 2 )) .venv-omni/bin/python bench/omni/score.py $k"
  scp -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    $USER_@$IP:docengine/results/$k/_omni_metrics.json results/$k/_omni_metrics.json
  # Per-page/per-table scores, for oracle and routing analysis.
  mkdir -p results/$k/_omni_pp
  scp -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    "$USER_@$IP:docengine/vendor/OmniDocBench/result/${k}_quick_match_*_per_*.json" results/$k/_omni_pp/ || true
  echo "$k scored in $(( $(date +%s) - t0 ))s"
done

# Comparison table from the pulled metrics (no re-run: score.py skips keys that already have _omni_metrics.json).
.venv-omni/bin/python bench/omni/score.py "$@"
