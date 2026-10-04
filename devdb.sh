#!/usr/bin/env bash
# devdb.sh — helper for installing Docker/Compose, updating the repo, and managing DevDB.
#
# Usage:
#   ./devdb.sh --install          Install Docker Engine + Compose plugin (major Linux distros)
#   ./devdb.sh --update           git pull (current branch) and rebuild/restart containers
#   ./devdb.sh --uninstall        Stop stack, remove project containers/images/volumes (optional Docker uninstall)
#   ./devdb.sh --up               docker compose up -d --build
#   ./devdb.sh --down             docker compose down
#   ./devdb.sh --logs             Follow app logs
#   ./devdb.sh --status           Show compose status
#   ./devdb.sh --help
#
# Environment:
#   REPO_URL   Override git remote for --update (default: origin of this checkout)
#   BRANCH     Branch to pull on --update (default: current branch)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}==>${NC} $*"; }
ok()    { echo -e "${GREEN}==>${NC} $*"; }
warn()  { echo -e "${YELLOW}==>${NC} $*"; }
err()   { echo -e "${RED}==>${NC} $*" >&2; }
die()   { err "$*"; exit 1; }

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      SUDO="sudo"
    else
      die "This action needs root. Install sudo or re-run as root."
    fi
  else
    SUDO=""
  fi
}

run() {
  if [[ -n "${SUDO:-}" ]]; then
    # shellcheck disable=SC2086
    $SUDO "$@"
  else
    "$@"
  fi
}

detect_distro() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="${ID:-unknown}"
    DISTRO_LIKE="${ID_LIKE:-}"
    DISTRO_VERSION_ID="${VERSION_ID:-}"
    DISTRO_CODENAME="${VERSION_CODENAME:-}"
  else
    DISTRO_ID="unknown"
    DISTRO_LIKE=""
    DISTRO_VERSION_ID=""
    DISTRO_CODENAME=""
  fi
}

have_docker() {
  command -v docker >/dev/null 2>&1
}

have_compose() {
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    die "Docker Compose not found. Run: $0 --install"
  fi
}

ensure_env_file() {
  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      warn ".env missing — copying from .env.example"
      cp .env.example .env
      warn "Edit .env (at least POSTGRES_PASSWORD, SECRET_KEY, TMDB keys) before production use."
    else
      die ".env and .env.example are both missing."
    fi
  fi
}

install_prereqs_debian() {
  run apt-get update -y
  run apt-get install -y ca-certificates curl gnupg lsb-release git
}

install_prereqs_rhel() {
  if command -v dnf >/dev/null 2>&1; then
    run dnf install -y dnf-plugins-core curl git ca-certificates
  else
    run yum install -y yum-utils curl git ca-certificates
  fi
}

install_prereqs_suse() {
  run zypper refresh
  run zypper install -y curl git ca-certificates
}

install_prereqs_arch() {
  run pacman -Sy --noconfirm curl git ca-certificates
}

install_docker_debian() {
  install_prereqs_debian

  # Official Docker apt repository
  run install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
    curl -fsSL "https://download.docker.com/linux/${DISTRO_ID}/gpg" | run gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    run chmod a+r /etc/apt/keyrings/docker.gpg
  fi

  local arch codename
  arch="$(dpkg --print-architecture)"
  codename="${DISTRO_CODENAME:-}"
  if [[ -z "$codename" ]]; then
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-stable}")"
  fi

  # Ubuntu and Debian share the same layout under download.docker.com/linux/{ubuntu,debian}
  local docker_distro="$DISTRO_ID"
  case "$DISTRO_ID" in
    ubuntu|debian) ;;
    linuxmint|pop|elementary|zorin)
      docker_distro="ubuntu"
      codename="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$codename}")"
      ;;
    raspbian)
      docker_distro="debian"
      ;;
    *)
      # Fall back to ubuntu repo for unknown Debian-like IDs
      if [[ "$DISTRO_LIKE" == *debian* || "$DISTRO_LIKE" == *ubuntu* ]]; then
        docker_distro="ubuntu"
      fi
      ;;
  esac

  echo \
    "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${docker_distro} ${codename} stable" \
    | run tee /etc/apt/sources.list.d/docker.list >/dev/null

  run apt-get update -y
  run apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

install_docker_rhel() {
  install_prereqs_rhel

  local repo_url
  case "$DISTRO_ID" in
    fedora)
      repo_url="https://download.docker.com/linux/fedora/docker-ce.repo"
      ;;
    centos|rhel|rocky|almalinux|ol)
      repo_url="https://download.docker.com/linux/centos/docker-ce.repo"
      ;;
    *)
      repo_url="https://download.docker.com/linux/centos/docker-ce.repo"
      ;;
  esac

  if command -v dnf >/dev/null 2>&1; then
    run dnf config-manager --add-repo "$repo_url" || true
    run dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    run yum-config-manager --add-repo "$repo_url" || true
    run yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  fi
}

install_docker_suse() {
  install_prereqs_suse
  # openSUSE: docker + compose plugin from distribution packages when available
  if run zypper search -x docker-compose-plugin >/dev/null 2>&1; then
    run zypper install -y docker docker-compose-plugin
  else
    run zypper install -y docker docker-compose
  fi
}

install_docker_arch() {
  install_prereqs_arch
  run pacman -S --noconfirm docker docker-compose docker-buildx
}

install_docker_generic() {
  warn "Unknown distro (${DISTRO_ID}). Trying Docker convenience script (Docker Engine only)."
  warn "You may still need to install the Compose plugin manually."
  curl -fsSL https://get.docker.com | run sh
}

enable_docker() {
  if command -v systemctl >/dev/null 2>&1; then
    run systemctl enable --now docker || true
  fi

  # Allow current user to run docker without sudo (effective after re-login)
  if [[ -n "${SUDO_USER:-}" ]]; then
    run usermod -aG docker "$SUDO_USER" || true
    warn "User '$SUDO_USER' added to group 'docker'. Log out and back in for it to take effect."
  elif [[ "${EUID}" -ne 0 && -n "${USER:-}" ]]; then
    run usermod -aG docker "$USER" || true
    warn "User '$USER' added to group 'docker'. Log out and back in for it to take effect."
  fi
}

cmd_install() {
  need_root
  detect_distro
  info "Detected distro: ${DISTRO_ID} (like: ${DISTRO_LIKE:-n/a})"

  if have_docker && have_compose; then
    ok "Docker and Compose are already installed."
    docker --version || true
    docker compose version 2>/dev/null || docker-compose --version || true
    return 0
  fi

  case "$DISTRO_ID" in
    ubuntu|debian|linuxmint|pop|elementary|zorin|raspbian)
      install_docker_debian
      ;;
    fedora|centos|rhel|rocky|almalinux|ol|amzn)
      install_docker_rhel
      ;;
    opensuse*|sles)
      install_docker_suse
      ;;
    arch|manjaro|endeavouros|garuda)
      install_docker_arch
      ;;
    *)
      if [[ "$DISTRO_LIKE" == *debian* || "$DISTRO_LIKE" == *ubuntu* ]]; then
        install_docker_debian
      elif [[ "$DISTRO_LIKE" == *rhel* || "$DISTRO_LIKE" == *fedora* || "$DISTRO_LIKE" == *centos* ]]; then
        install_docker_rhel
      elif [[ "$DISTRO_LIKE" == *suse* ]]; then
        install_docker_suse
      elif [[ "$DISTRO_LIKE" == *arch* ]]; then
        install_docker_arch
      else
        install_docker_generic
      fi
      ;;
  esac

  enable_docker

  if have_docker && have_compose; then
    ok "Docker + Compose installed successfully."
    docker --version
    docker compose version 2>/dev/null || docker-compose --version
  elif have_docker; then
    warn "Docker is installed but Compose plugin was not detected."
    warn "Try: sudo apt/dnf/pacman install docker-compose-plugin  (package name varies by distro)"
  else
    die "Installation finished but 'docker' is not on PATH. Check the installer output above."
  fi

  ensure_env_file
  ok "Next: edit .env if needed, then run: $0 --up"
}

cmd_update() {
  if ! command -v git >/dev/null 2>&1; then
    die "git is required for --update. Install git or run --install first."
  fi
  if [[ ! -d .git ]]; then
    die "Not a git checkout (no .git directory). Clone the repo first."
  fi

  local branch
  branch="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
  info "Updating branch: $branch"

  git fetch --all --prune
  git pull --ff-only "${REPO_URL:-origin}" "$branch" || git pull --ff-only

  if have_docker && have_compose; then
    ensure_env_file
    info "Rebuilding and restarting containers..."
    compose up -d --build
    ok "Stack updated and running."
    compose ps
  else
    warn "Docker/Compose not available — repo updated only. Run --install then --up."
  fi
}

cmd_uninstall() {
  need_root

  if have_docker && have_compose; then
    info "Stopping DevDB stack and removing project resources..."
    compose down --remove-orphans 2>/dev/null || true
    # Named volume from docker-compose.yml
    run docker volume rm devdb_postgres_data 2>/dev/null || true
    # Project images (best-effort)
    local images
    images="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'devdb' || true)"
    if [[ -n "$images" ]]; then
      # shellcheck disable=SC2086
      run docker rmi $images 2>/dev/null || true
    fi
    ok "DevDB containers/volumes cleaned up (best-effort)."
  else
    warn "Docker not available; skipping container cleanup."
  fi

  echo
  read -r -p "Also uninstall Docker Engine from this system? [y/N] " ans
  case "${ans:-N}" in
    y|Y|yes|YES)
      detect_distro
      info "Removing Docker packages for ${DISTRO_ID}..."
      case "$DISTRO_ID" in
        ubuntu|debian|linuxmint|pop|elementary|zorin|raspbian)
          run apt-get purge -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-compose 2>/dev/null || true
          run apt-get autoremove -y 2>/dev/null || true
          ;;
        fedora|centos|rhel|rocky|almalinux|ol|amzn)
          if command -v dnf >/dev/null 2>&1; then
            run dnf remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null || true
          else
            run yum remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin 2>/dev/null || true
          fi
          ;;
        opensuse*|sles)
          run zypper remove -y docker docker-compose docker-compose-plugin 2>/dev/null || true
          ;;
        arch|manjaro|endeavouros|garuda)
          run pacman -Rns --noconfirm docker docker-compose docker-buildx 2>/dev/null || true
          ;;
        *)
          warn "Unknown distro — remove Docker packages manually."
          ;;
      esac
      ok "Docker package removal attempted."
      ;;
    *)
      info "Left Docker Engine installed."
      ;;
  esac

  echo
  read -r -p "Delete this project directory (${SCRIPT_DIR})? [y/N] " ans2
  case "${ans2:-N}" in
    y|Y|yes|YES)
      info "Removing ${SCRIPT_DIR}..."
      cd /tmp
      run rm -rf "$SCRIPT_DIR"
      ok "Project directory removed."
      ;;
    *)
      info "Kept project files."
      ;;
  esac
}

cmd_up() {
  have_docker || die "Docker not found. Run: $0 --install"
  have_compose || die "Compose not found. Run: $0 --install"
  ensure_env_file
  compose up -d --build
  ok "DevDB is up (http://localhost:8000 by default)."
  compose ps
}

cmd_down() {
  have_docker || die "Docker not found."
  compose down
  ok "Stack stopped."
}

cmd_logs() {
  have_docker || die "Docker not found."
  compose logs -f app
}

cmd_status() {
  have_docker || die "Docker not found."
  compose ps
}

usage() {
  cat <<EOF
DevDB helper script

Usage: $0 [flag]

  --install     Install Docker Engine + Compose (Debian/Ubuntu, RHEL/Fedora/Rocky,
                openSUSE, Arch, and derivatives). Creates .env from .env.example if needed.
  --update      git pull current branch and rebuild/restart the stack
  --uninstall   Stop stack, remove DevDB volumes/images; optional Docker + directory removal
  --up          Build and start (docker compose up -d --build)
  --down        Stop stack
  --logs        Follow app container logs
  --status      Show compose service status
  --help        Show this help

Examples:
  chmod +x devdb.sh
  ./devdb.sh --install
  # edit .env
  ./devdb.sh --up
  ./devdb.sh --update
  ./devdb.sh --uninstall
EOF
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 1
  fi

  case "$1" in
    --install|-i)   cmd_install ;;
    --update|-u)    cmd_update ;;
    --uninstall)    cmd_uninstall ;;
    --up)           cmd_up ;;
    --down)         cmd_down ;;
    --logs)         cmd_logs ;;
    --status)       cmd_status ;;
    --help|-h)      usage ;;
    *)
      err "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
}

main "$@"
