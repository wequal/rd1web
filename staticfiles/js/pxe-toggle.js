document.addEventListener('DOMContentLoaded', function () {
  const check = document.getElementById("id_check");
  const remove = document.getElementById("id_remove");

  if (check && remove) {
    check.addEventListener("change", function () {
      if (this.checked) remove.checked = false;
    });

    remove.addEventListener("change", function () {
      if (this.checked) check.checked = false;
    });
  }
});

