# Nova OS Technical Roadmap

## Base Platform Selection
- **Distribution**: Fedora 43 aarch64 Atomic (rpm-ostree). Provides immutable base, atomic updates, ARMv8 server/workstation tuning.
- **Initial Hardware Target**: Ampere-based high-end workstation with discrete GPU (AMD RDNA/Intel Arc) and NVMe storage.
- **Build Infrastructure**:
  - Mirror Fedora 43 Atomic repositories internally; maintain Nova-specific rpm-ostree remote.
  - Stand up Koji + Pungi or Fedora CoreOS-style pipeline for custom composes.
  - Automate image builds (workstation, devkit) using `cosa`/`coreos-assembler` adaptations.

## Bootstrapping Fedora 43 Atomic
1. **Inspect available images**
   ```bash
   ./scripts/fetch_fedora_atomic.py --version 43 --channel any --limit 3
   ```
   The helper queries Fedora's `releases.json` feed and prints Atomic artifacts for `aarch64`. Run it in CI to detect when stable (non-Beta) media becomes available.

2. **Download the desired artifact**
   ```bash
   ./scripts/fetch_fedora_atomic.py --version 43 --channel beta --download --output artifacts/
   ```
   Replace `--channel beta` with `stable` once Fedora publishes the final Atomic release. Downloads are stored in `artifacts/` with progress feedback.

3. **Verify integrity before use**
   ```bash
   sha256sum artifacts/Fedora-COSMIC-Atomic-ostree-aarch64-43_Beta-1.3.iso
   ```
   Compare the checksum with the value printed by the helper. Automate this check in the Nova OS build pipeline prior to importing the image.

4. **Seed Nova's OSTree mirror**
   - Loop-mount the ISO (`sudo mount -o loop`) or extract OCI archives with `podman pull oci-archive:...`.
   - Synchronize the embedded OSTree repo into Nova's remote using `ostree pull-local`.
   - Record upstream commit hashes so downstream composes are reproducible.

5. **Kick off Nova customization**
   - Layer Nova branding RPMs via `rpm-ostree install --idempotent ...`.
   - Create an initial OSTree commit with `rpm-ostree commit --tree=ref=... --branch=nova/43/workstation` as the baseline for subsequent Nova-specific composes.

6. **Verify the upstream image boots under QEMU**
   ```bash
   ./scripts/boot_fedora_atomic.py \
     --iso artifacts/Fedora-COSMIC-Atomic-ostree-aarch64-43_Beta-1.3.iso \
     --boot-wait 150
   ```
   The helper provisions a temporary qcow2 disk, boots the ISO headlessly with SDL's dummy driver, then captures a PNG screenshot
   and serial console log inside `artifacts/boot/`. Use the screenshot to document baseline behaviour (e.g., GRUB splash) and the
   serial log for automated smoke tests. Increase `--boot-wait` if you need to capture a later boot stage. Ensure the host has
   `qemu-system-aarch64`, `qemu-efi-aarch64`, and ImageMagick's `convert` binary available.

## Governance & Compliance
- Form Nova OS architecture board (kernel, security, UX, platform leads).
- Track Fedora licensing obligations; ensure rpm-ostree layered packages comply with GPL/Apache terms.
- Establish contribution policy; upstream kernel/driver fixes where feasible.

## System Architecture
- **Kernel & Firmware**:
  - Maintain Fedora 43 aarch64 kernel with Nova patches (power management, GPU drivers, secure boot keys).
  - Integrate UEFI Secure Boot with Nova-signed keys; enable TPM-backed disk encryption by default.
- **Immutable Root**:
  - Utilize rpm-ostree layered packages for Nova components (UX shell, SDKs).
  - Define base packagesets: `nova-workstation`, `nova-core`, `nova-developer`.
- **Update Strategy**:
  - Host Nova OSTree remotes; implement staged rollouts and automatic rollbacks via `ostree admin rollback`.

## Nova UX & Branding
- Create Nova design system: typography, color palette, iconography, motion guidelines.
- Fork GNOME Shell (43-compatible) into Nova Shell with Wayland compositor customizations (multi-monitor, HDR).
- Replace Fedora branding assets (Plymouth theme, GDM, wallpapers) with Nova equivalents.
- Build responsive layouts for desktop, tablet, automotive, wearable shells sharing component library.

## Developer Experience
- Package Swift toolchain (5.10+) for aarch64 Fedora Atomic via layered RPMs and Flatpaks.
- Provide Nova SDK containing Swift UI frameworks, template projects, and CLI (`nova-sdk`) integrated with VS Code extensions.
- Offer containerized dev environments using Podman with rpm-ostree overrides for rapid iteration.

## Compatibility Layers
- **x86_64 Translation**: Integrate FEX-Emu with rpm-ostree layering; ship Nova Compatibility Manager GUI to configure per-app profiles.
- **Windows Applications**: Bundle Proton/Wine patched for FEX; supply ProtonDB-like compatibility database.
- **Android Apps**: Embed Waydroid (Android 13) images with GPU acceleration; bridge Nova notification and input services.

## Security & Services
- Harden SELinux policies for nova-shell, compatibility daemons, and Waydroid.
- Implement Nova Identity (SSO) integration for cloud sync, settings roaming.
- Provide encrypted Nova Cloud backups via OSTree snapshots and user data sync.

## Testing & Validation
- Establish CI with GitLab runners on Ampere servers executing rpm-ostree compose tests.
- Automate smoke tests: boot verification, GNOME/Nova Shell UI tests, Swift sample builds, FEX/Proton regression suites.
- Maintain hardware lab matrix (workstation, laptop, tablet devkit) for driver validation.

## Release Phasing
1. **Phase 0**: Fedora 43 Atomic baseline, branding swap, OSTree pipeline online.
2. **Phase 1**: Nova Shell alpha, Swift SDK preview, initial x86 translation POC.
3. **Phase 2**: Windows/Android compatibility betas, Nova Cloud services integration.
4. **Phase 3**: Mobile/automotive form factor adaptations, public developer preview.
5. **Phase 4**: General availability with enterprise support and continuous updates.

## Documentation & Community
- Publish Nova OS developer portal with rpm-ostree layering guides, SDK docs, compatibility matrix.
- Create feedback channels (Discourse, bug tracker) and beta opt-in program.
- Maintain transparent changelogs for each OSTree release.

