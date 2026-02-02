const year_dict = {
    "2023-2024" : "2324",
    "2024-2025" : "2425",
    "2025-2026" : "2526"
}
function getYear() {
    try {
        const stored = localStorage.getItem("year");
        if (stored in year_dict) {
            const value = year_dict[stored];
            return value
        }
    } catch (e) {}
  }

  function updateNavLinks(selectedYear) {
    const navLinks = document.querySelectorAll('.dynamic-nav-item');
    
    navLinks.forEach(link => {
        const template = link.getAttribute('data-url-template');
        // Replace the placeholder with the value from your dropdown/localStorage
        link.href = template.replace('YEAR_VAL', selectedYear);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const selector = document.getElementById('year-select');
    
    // 1. Get existing year from storage or fall back to the dropdown's default selection
    let currentYear = localStorage.getItem("year");

    if (!currentYear) {
        // If storage is empty, initialize it with the current dropdown value (e.g., "2526")
        currentYear = selector.value;
        localStorage.setItem("year", currentYear);
    } else {
        // If storage has a value, make sure the dropdown matches it
        selector.value = currentYear;
    }

    // 2. Initial run to update navigation links based on this year
    updateNavLinks(currentYear);

    // 3. Listen for future changes
    selector.addEventListener('change', (e) => {
        const newValue = e.target.value;
        localStorage.setItem("year", newValue);
        updateNavLinks(newValue);
    });
});

selector.addEventListener('change', (e) => {
    const newYear = e.target.value;
    const oldYear = localStorage.getItem("year") || "2526"; // Fallback to your default
    
    localStorage.setItem("year", newYear);

    // Get the current URL path
    let currentPath = window.location.pathname;

    // If the current URL contains the old year, swap it and redirect
    if (currentPath.includes(oldYear)) {
        const newPath = currentPath.replace(oldYear, newYear);
        window.location.href = newPath;
    } else if (currentPath.includes("YEAR_VAL")) {
        // Handle cases where the placeholder might still be in the URL
        window.location.href = currentPath.replace("YEAR_VAL", newYear);
    } else {
        // If we aren't on a year-specific page, just update the nav links
        updateNavLinks(newYear);
    }
});