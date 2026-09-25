document.addEventListener('DOMContentLoaded', () => {
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach((el) => setTimeout(() => el.remove(), 4500));
});
