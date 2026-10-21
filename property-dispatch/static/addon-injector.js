/**
 * Post One Lawn Co. - User Autonomy Add-on Injector Component
 * Add-ons with their price shown up front, picked by the customer before booking.
 *
 *   <addon-injector></addon-injector>   fires "addonSelectionChange" (bubbles) with { binCleaning, gutterCleaning }
 *   Optional attributes: bin-price / gutter-price (from the server's price list) and selected="bin_cleaning gutters".
 */
class AddonInjector extends HTMLElement {
    constructor() {
        super();
        this.state = { binCleaning: false, gutterCleaning: false };
    }

    static get observedAttributes() { return ["bin-price", "gutter-price"]; }

    // Prices can arrive after the cards are drawn (from the server's price list).
    attributeChangedCallback(name, _old, value) {
        const el = this.querySelector(`#addon-${name === "bin-price" ? "bin" : "gutter"}-card .addon-price`);
        if (el && value != null) el.textContent = `+$${Number(value).toFixed(0)}`;
    }

    // Set the picks from outside (e.g. a booking link with ?addon=gutters) without firing the change event.
    select(keys) {
        this.state.binCleaning = keys.includes("bin_cleaning");
        this.state.gutterCleaning = keys.includes("gutters");
        this.updateUI("binCleaning");
        this.updateUI("gutterCleaning");
    }

    connectedCallback() {
        const picked = (this.getAttribute("selected") || "").split(/\s+/);
        this.state.binCleaning = picked.includes("bin_cleaning");
        this.state.gutterCleaning = picked.includes("gutters");
        this.render();
        this.setupListeners();
        this.updateUI("binCleaning");
        this.updateUI("gutterCleaning");
    }

    setupListeners() {
        // Cards work with a tap, a click, or Space / Enter from the keyboard.
        for (const [id, key] of [["#addon-bin-card", "binCleaning"], ["#addon-gutter-card", "gutterCleaning"]]) {
            const card = this.querySelector(id);
            card?.addEventListener("click", () => this.toggleAddon(key));
            card?.addEventListener("keydown", (e) => {
                if (e.key === " " || e.key === "Enter") { e.preventDefault(); this.toggleAddon(key); }
            });
        }
    }

    toggleAddon(addonKey) {
        this.state[addonKey] = !this.state[addonKey];

        // Dispatch structured event back to main app pricing matrix pipeline
        this.dispatchEvent(new CustomEvent("addonSelectionChange", {
            bubbles: true,
            detail: { ...this.state }
        }));

        this.updateUI(addonKey);
    }

    updateUI(addonKey) {
        const card = this.querySelector(`#addon-${addonKey === "binCleaning" ? "bin" : "gutter"}-card`);
        if (!card) return;
        const on = this.state[addonKey];
        card.classList.toggle("is-on", on);
        card.setAttribute("aria-checked", String(on));
    }

    render() {
        const price = (name) => `+$${Number(this.getAttribute(name) || 15).toFixed(0)}`;
        this.innerHTML = `
            <div class="addon-injector">
                <div class="addon-head">
                    <span class="addon-kicker">Configure Your Operation</span>
                    <h3>Select Instant Add-Ons</h3>
                    <p>Zero phone tag. Zero drive-by guessing games. Run your service your way.</p>
                </div>

                <div class="addon-grid">
                    <!-- Bin Cleaning Module -->
                    <div id="addon-bin-card" class="addon-card" role="checkbox" aria-checked="false" tabindex="0" aria-labelledby="addon-bin-title">
                        <div class="addon-top">
                            <div>
                                <h3 id="addon-bin-title">Bin Sanitization</h3>
                                <p>Clean, deodorize, and kill bacteria setup.</p>
                            </div>
                            <span class="addon-price">${price("bin-price")}</span>
                        </div>
                        <div class="addon-check">
                            <span class="addon-box" id="checkbox-binCleaning" aria-hidden="true"></span>
                            <span>Add to current visit</span>
                        </div>
                    </div>

                    <!-- Gutter Cleaning Module -->
                    <div id="addon-gutter-card" class="addon-card" role="checkbox" aria-checked="false" tabindex="0" aria-labelledby="addon-gutter-title">
                        <div class="addon-top">
                            <div>
                                <h3 id="addon-gutter-title">Gutter Clearance</h3>
                                <p>Clear downspouts to restore water flow.</p>
                            </div>
                            <span class="addon-price">${price("gutter-price")}</span>
                        </div>
                        <div class="addon-check">
                            <span class="addon-box" id="checkbox-gutterCleaning" aria-hidden="true"></span>
                            <span>Add to current visit</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

customElements.define("addon-injector", AddonInjector);
