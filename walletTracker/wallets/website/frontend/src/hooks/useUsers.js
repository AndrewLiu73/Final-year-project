import { useState, useEffect } from "react";

function useUserId() {
    const [userId, setUserId] = useState(null);

    useEffect(() => {
        let id = localStorage.getItem("hl_user_id");
        if (!id) {
            id = crypto.randomUUID();
            localStorage.setItem("hl_user_id", id);
        }
        setUserId(id);
    }, []);

    return userId;
}

export default useUserId;
