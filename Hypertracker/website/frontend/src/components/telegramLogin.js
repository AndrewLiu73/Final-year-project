import { useEffect } from 'react';


export default function TelegramLogin({ onAuth }) {
    useEffect(() => {
        window.onTelegramAuth = (user) => {
            fetch(`http://localhost:8000/api/auth/telegram`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(user),
            })
            .then(res => res.json())
            .then(data => {
                localStorage.setItem("user_id", data.user_id);
                localStorage.setItem("user_name", data.name);
                onAuth(data);
            });
        };

        const script = document.createElement("script");
        script.src = "https://telegram.org/js/telegram-widget.js?22";
        script.setAttribute("data-telegram-login", "HyperTrack_Alert_Bot");
        script.setAttribute("data-size", "large");
        script.setAttribute("data-onauth", "onTelegramAuth(user)");
        script.setAttribute("data-request-access", "write");
        script.async = true;
        document.getElementById("tg-login").appendChild(script);
    }, []);

    return <div id="tg-login" />;
}
