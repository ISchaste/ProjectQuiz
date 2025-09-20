// static/js/search.js
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".char-input").forEach(input => {
        const suggestions = input.parentNode.querySelector(".search-suggestions");
        const mode = input.dataset.mode || "classic"; // читаем режим из data-атрибута

        function loadSuggestions(q) {
            fetch(`/search_characters?query=${encodeURIComponent(q)}&mode=${encodeURIComponent(mode)}`)
                .then(res => res.json())
                .then(data => {
                    suggestions.innerHTML = "";
                    if (data.length > 0) {
                        data.forEach(item => {
                            const div = document.createElement("div");
                            div.className = "search-item";
                            div.innerHTML = `<img src="${item.avatar}" alt="${item.name}"><span>${item.name}</span>`;
                            div.onclick = () => {
                                input.value = item.name;
                                input.closest("form").submit();
                            };
                            suggestions.appendChild(div);
                        });
                        suggestions.style.display = "block";
                    } else {
                        suggestions.style.display = "none";
                    }
                });
        }

        input.addEventListener("focus", () => loadSuggestions(input.value.trim()));
        input.addEventListener("input", () => loadSuggestions(input.value.trim()));

        document.addEventListener("click", e => {
            if (!suggestions.contains(e.target) && e.target !== input) {
                suggestions.style.display = "none";
            }
        });
    });
});
