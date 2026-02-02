const year_dict = {
    "2023-2024" : "2324",
    "2024-2025" : "2425",
    "2025-2026" : "2526"
};

function updateNavLinks(selectedYear) {
    const navLinks = document.querySelectorAll('.dynamic-nav-item');
    navLinks.forEach(link => {
        const template = link.getAttribute('data-url-template');
        if (template) {
            link.href = template.replace('YEAR_VAL', selectedYear);
        }
    });
}

function getYear() {
    try {
        const stored = localStorage.getItem("year");
        if (Object.values(year_dict).includes(stored)) return stored;
    } catch (e) {}
    const selector = document.getElementById("year-select");
    return selector ? selector.value : "2526";
}

document.addEventListener('DOMContentLoaded', () => {
    const selector = document.getElementById('year-select');
    if (!selector) return;

    const currentYear = getYear();
    selector.value = currentYear;
    localStorage.setItem("year", currentYear);
    updateNavLinks(currentYear);

    selector.addEventListener('change', (e) => {
        const newYear = e.target.value;
        const oldYear = localStorage.getItem("year");
        localStorage.setItem("year", newYear);

        const currentPath = window.location.pathname;

        // 1. If we are on a year-specific page, swap and redirect
        if (oldYear && currentPath.includes(oldYear)) {
            window.location.href = currentPath.replace(oldYear, newYear);
        } 
        // 2. NEW: If on the Root Homepage, redirect to the Season Home (e.g., /2526/index.html)
        else if (currentPath === "/" || currentPath === "/index.html") {
            window.location.href = `/${newYear}/index.html`;
        }
        // 3. Fallback: Force refresh for general pages (like /about.html)
        else {
            updateNavLinks(newYear);
            window.location.reload();
        }
    });
});
