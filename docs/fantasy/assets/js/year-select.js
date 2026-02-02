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

// Initialization and Event Listening
document.addEventListener('DOMContentLoaded', () => {
    const selector = document.getElementById('year-select');
    
    // 1. Run on page load based on your getYear() logic
    updateNavLinks(getYear());

    // 2. Run whenever the user changes the dropdown
    selector.addEventListener('change', (e) => {
        const yearValue = e.target.value;
        localStorage.setItem("year", yearValue); // Sync with your getYear() logic
        updateNavLinks(yearValue);
    });
});