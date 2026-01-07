function normText(s) {
  return (s || "")
    .replace(/\u00A0/g, " ")     // NBSP -> space
    .replace(/\s+/g, " ")       // collapse whitespace
    .trim();
}

function setChangeDiv(type, inj, btn) {
  const options = {
    "All": "all",
    "Best": "best",
    "Worst": "worst"
  };

  const inj_options = {
    "Injuries" : "inj",
    "No Injuries" : "noing"
  };

  document.querySelectorAll(".table-scroll").forEach(div => {
    div.classList.add("hidden-div");
  })

  // Get all tables with the class "table-scroll"
  const target = document.querySelector(`.table-scroll .${options[type]} .${inj_options[inj]}`);
  if (target) target.classList.remove("hidden-div");

  // active button styling
  if (btn.classList.contains("type-toggle")) {
    document.querySelectorAll(".type-toggle button").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
  }
  
  // active button styling
  if (btn.classList.contains("injury-toggle")) {
    document.querySelectorAll(".injury-toggle button").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
  }
}

// default = whatever button has class active (yours is 2 Weeks)
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".type-toggle button").forEach(btn => {
        btn.addEventListener("click", () => {
            const type = btn.getAttribute("data-key");
            document.querySelectorAll(".injury-toggle button").forEach(btn => {
                if (btn.classList.contains("active")){
                    setChangeDiv(type, btn.getAttribute("data-key"), btn)
                }
            })
        })
    })
  const defaultTypeBtn = document.querySelector(".type-toggle button.active");
  if (defaultTypeBtn) defaultTypeBtn.click();

  document.querySelectorAll(".injury-toggle button").forEach(btn => {
        btn.addEventListener("click", () => {
            const inj = btn.getAttribute("data-key");
            document.querySelectorAll(".type-toggle button").forEach(btn => {
                if (btn.classList.contains("active")){
                    setChangeDiv(btn.getAttribute("data-key"), inj, btn)
                }
            })
        })
    })
  const defaultInjBtn = document.querySelector(".injury-toggle button.active");
  if (defaultInjBtn) defaultInjBtn.click();
});