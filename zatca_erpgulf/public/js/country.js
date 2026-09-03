// Shared country normalization for ZATCA client-side checks.
// Accepts ERPNext Country names and ISO-like values without changing stored data.
window.zatca_normalize_country_code = window.zatca_normalize_country_code || function (value) {
    const normalized = String(value || "").trim().toLowerCase();
    if (!normalized) return "";
    if (["sa", "s.a.", "saudi arabia", "kingdom of saudi arabia"].includes(normalized)) return "SA";
    if (/^[a-z]{2}$/.test(normalized)) return normalized.toUpperCase();
    return normalized;
};

window.zatca_is_saudi_country = window.zatca_is_saudi_country || function (value) {
    return window.zatca_normalize_country_code(value) === "SA";
};
