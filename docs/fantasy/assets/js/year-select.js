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