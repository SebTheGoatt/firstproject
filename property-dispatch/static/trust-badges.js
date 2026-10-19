/**
 * Post One Lawn Co. - Professional Credential Validation Component
 * Leverages elite military, technical, and regulatory pedigree to lock in premium trust.
 *
 *   <trust-badges coverage="$1M/$2M" background-checked></trust-badges>
 *   The insurance and background lines show only when the server sets them (LIABILITY_COVERAGE /
 *   CREW_BACKGROUND_CHECKED in Render), so the page never claims coverage that isn't in force.
 */
class TrustBadges extends HTMLElement {
    connectedCallback() {
        const coverage = (this.getAttribute("coverage") || "").trim();
        const footer = ["🔒 Encrypted Stripe Checkout", coverage ? `Insured (${coverage})` : null,
                        this.hasAttribute("background-checked") ? "Background-Checked Crew" : null, "Veteran-Led"]
            .filter(Boolean).join(" · ");
        const badge = (icon, title, text) => `
                    <div class="tb-item">
                        <div class="tb-icon" aria-hidden="true">${icon}</div>
                        <div>
                            <h5>${title}</h5>
                            <p>${text}</p>
                        </div>
                    </div>`;
        this.innerHTML = `
            <div class="trust-badges">
                <div class="tb-head">
                    <h4>Institutional Ground Truth</h4>
                    <h3>Operational Pedigree &amp; Security</h3>
                </div>
                <div class="tb-grid">
                    ${badge("🎖️", "Veteran-Owned", "Locally owned and run by a U.S. Marine veteran.")}
                    ${badge("🧠", "AI Infrastructure", "Founder trained in NVIDIA AI Infrastructure &amp; Operations; routes planned by our own optimization software.")}
                    ${badge("🛡️", "OSHA 30 Trained", "Job-site safety and risk mitigation run to OSHA 30-hour training standards.")}
                    ${badge("📈", "Data Systems", "Schedules tracked with Google Project Management and IBM Data Science certificate methods.")}
                </div>
                <div class="tb-foot"><p>${footer}</p></div>
            </div>
        `;
    }
}

customElements.define("trust-badges", TrustBadges);
