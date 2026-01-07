const buttonGroup = document.getElementById('typeButtonGroup');
const buttons = buttonGroup.querySelectorAll('button');

buttons.forEach(button => {
    button.addEventListener('click', function() {
        buttons.forEach(btn => btn.classList.remove('active'));
        this.classList.add('active');
        const selectedOption = this.getAttribute('data-option');
    });
});