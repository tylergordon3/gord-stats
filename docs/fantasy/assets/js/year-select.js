const year_dict = {
    "2023-2024" : "2324",
    "2024-2025" : "2425",
    "2025-2026" : "2526"
};

/**
 * Updates all links with the 'dynamic-nav-item' class
 * by replacing 'YEAR_VAL' in their template with the chosen year.
 */
function updateNavLinks(selectedYear) {
    const navLinks = document.querySelectorAll('.dynamic-nav-item');
    navLinks.forEach(link => {
        const template = link.getAttribute('data-url-template');
        if (template) {
            link.href = template.replace('YEAR_VAL', selectedYear);
        }
    });
}

/**
 * Gets current year from localStorage or falls back to dropdown default.
 */
function getYear() {
    try {
        const stored = localStorage.getItem("year");
        // Check if stored value is a valid code (e.g., "2425")
        if (Object.values(year_dict).includes(stored)) {
            return stored;
        }
    } catch (e) {}

    // Fallback to the value attribute of the select element
    const selector = document.getElementById("year-select");
    return selector ? selector.value : "2526";
}

document.addEventListener('DOMContentLoaded', () => {
    const selector = document.getElementById('year-select');
    if (!selector) return;

    // 1. Initialize state
    const currentYear = getYear();
    selector.value = currentYear;
    localStorage.setItem("year", currentYear);
    updateNavLinks(currentYear);

    // 2. Handle Year Changes
    selector.addEventListener('change', (e) => {
        const newYear = e.target.value;
        const oldYear = localStorage.getItem("year");
        
        localStorage.setItem("year", newYear);

        const currentPath = window.location.pathname;

        // If we are on a page that includes the year code in the URL, redirect
        if (oldYear && currentPath.includes(oldYear)) {
            const newPath = currentPath.replace(oldYear, newYear);
            
            // Check if the page exists before redirecting
            fetch(newPath, { method: 'HEAD' }).then(response => {
                window.location.href = response.ok ? newPath : "/404.html";
            }).catch(() => {
                window.location.href = newPath;
            });
        } else {
            // Otherwise, just update the menu links without refreshing
            updateNavLinks(newYear);
        }
    });
});