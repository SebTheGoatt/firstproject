/**
 * Post One Lawn Co. - Front-End Logistics Controller
 * Orchestrates dynamic pricing engine queries and feeds the Stripe payloads.
 */
const SemperGreenEngine = {
    state: {
        address: "",
        lat: 30.0102,  // Extracted via address verification maps step
        lng: -95.4201, // Extracted via address verification maps step
        lotSizeSqft: 5000,
        complexity: "STANDARD",
        binCleaning: false,
        gutterCleaning: false
    },

    init() {
        console.log("Post One pricing engine ready");
        this.bindEvents();
    },

    // Called by the page's address step (Google dropdown) with the picked address.
    setLocation(address, lat, lng) {
        this.state.address = address;
        this.state.lat = lat;
        this.state.lng = lng;
        this.fetchDynamicPricing();
    },

    bindEvents() {
        // Event Listeners for UI interaction nodes
        document.getElementById("calculate-price-btn")?.addEventListener("click", () => this.fetchDynamicPricing());

        document.getElementById("lot-size-select")?.addEventListener("change", (e) => {
            this.state.lotSizeSqft = parseFloat(e.target.value);
            this.fetchDynamicPricing();
        });

        document.getElementById("complexity-select")?.addEventListener("change", (e) => {
            this.state.complexity = e.target.value;
            this.fetchDynamicPricing();
        });

        // Add-on cards (<addon-injector>) report every change here
        document.addEventListener("addonSelectionChange", (e) => {
            this.state.binCleaning = e.detail.binCleaning;
            this.state.gutterCleaning = e.detail.gutterCleaning;
            this.fetchDynamicPricing();
        });

        // Addon checkbox hooks
        document.getElementById("toggle-bins")?.addEventListener("change", (e) => {
            this.state.binCleaning = e.target.checked;
            this.fetchDynamicPricing();
        });

        document.getElementById("toggle-gutters")?.addEventListener("change", (e) => {
            this.state.gutterCleaning = e.target.checked;
            this.fetchDynamicPricing();
        });
    },

    async fetchDynamicPricing() {
        const displayContainer = document.getElementById("pricing-breakdown-display");
        const checkoutTotalLabel = document.getElementById("checkout-total-anchor");

        try {
            const response = await fetch("/api/v1/calculate-yield-price", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    street_address: this.state.address || document.getElementById("address-input")?.value || "Spring, TX",
                    latitude: this.state.lat,
                    longitude: this.state.lng,
                    lot_size_sqft: this.state.lotSizeSqft,
                    complexity_rating: this.state.complexity,
                    has_bin_cleaning: this.state.binCleaning,
                    has_gutter_cleaning: this.state.gutterCleaning
                })
            });

            if (!response.ok) throw new Error("Validation pipeline exception logged.");

            const data = await response.json();
            this.renderPricingMatrix(data, displayContainer, checkoutTotalLabel);

        } catch (error) {
            console.error("❌ Yield Engine Matrix Fault:", error);
            if (displayContainer) {
                displayContainer.innerHTML = `<p class="text-red-500">Error mapping system density coordinates.</p>`;
            }
        }
    },

    renderPricingMatrix(data, container, anchorLabel) {
        if (!container) return;

        // Dynamic rendering using Coca-Cola premium framing rules
        container.innerHTML = `
            <div class="space-y-2 p-4 bg-zinc-900 rounded-lg text-white border border-zinc-800">
                <div class="flex justify-between text-sm">
                    <span class="text-zinc-400">Logistics Deployment Fee Floor:</span>
                    <span class="font-mono">$${data.base_mow_fee.toFixed(2)}</span>
                </div>
                ${data.is_cluster_optimized ? `
                <div class="flex justify-between text-sm text-emerald-400">
                    <span>⚡ Route Cluster Optimization Benefit (${data.route_density_score} stops):</span> <span class="font-mono">-$${data.density_discount.toFixed(2)}</span>
                </div>` : `
                <div class="text-xs text-amber-500">
                    📍 Standalone Premium Density Target Area
                </div>`}
                <div class="flex justify-between text-sm">
                    <span class="text-zinc-400">Ancillary High-Margin Infrastructure Add-ons:</span>
                    <span class="font-mono">$${data.addons_total.toFixed(2)}</span>
                </div>
                <div class="border-t border-zinc-800 my-2 pt-2 flex justify-between text-sm">
                    <span class="text-zinc-400">Texas Sales Tax Allocation (8.25%):</span>
                    <span class="font-mono">$${data.sales_tax.toFixed(2)}</span>
                </div>
                <div class="flex justify-between text-base font-bold text-green-400">
                    <span>Guaranteed Enterprise Checkout Total:</span>
                    <span class="font-mono">$${data.final_checkout_total.toFixed(2)}</span>
                </div>
            </div>
        `;

        if (anchorLabel) {
            anchorLabel.innerText = `$${data.final_checkout_total.toFixed(2)}`;
        }
    }
};

document.addEventListener("DOMContentLoaded", () => SemperGreenEngine.init());
