'use strict';
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.3.1/firebase-app.js";
import { getAuth, createUserWithEmailAndPassword, signInWithEmailAndPassword, signOut } from "https://www.gstatic.com/firebasejs/11.3.1/firebase-auth.js";

const firebaseConfig = {
    apiKey: "",
    authDomain: "",
    projectId: "",
    storageBucket: "",
    messagingSenderId: "",
    appId: "",
    measurementId: ""
};

window.addEventListener("load", function () {
    const app = initializeApp(firebaseConfig);
    const auth = getAuth(app);
    updateUI(document.cookie);
    console.log("Firebase auth initialized");

    // Signup event listener
    const signUpButton = document.getElementById("sign-up");
    if (signUpButton) {
        signUpButton.addEventListener('click', function () {
            const email = document.getElementById("email").value;
            const password = document.getElementById("password").value;
            
            console.log("Attempting signup with:", email);

            createUserWithEmailAndPassword(auth, email, password)
                .then((userCredential) => {
                    const user = userCredential.user;
                    console.log("Signup successful");
                    user.getIdToken().then((token) => {
                        document.cookie = "token=" + token + ";path=/;SameSite=Strict";
                        window.location = "/";
                    });
                })
                .catch((error) => {
                    console.log("Signup error:", error.code, error.message);
                    alert("Sign up error: " + error.message);
                });
        });
    }

    // Login event listener
    const loginButton = document.getElementById("login");
    if (loginButton) {
        loginButton.addEventListener('click', function () {
            const email = document.getElementById("email").value;
            const password = document.getElementById("password").value;
            
            console.log("Attempting login with:", email);

            signInWithEmailAndPassword(auth, email, password)
                .then((userCredential) => {
                    const user = userCredential.user;
                    console.log("Login successful");
                    user.getIdToken().then((token) => {
                        document.cookie = "token=" + token + ";path=/;SameSite=Strict";
                        window.location = "/";
                    });
                })
                .catch((error) => {
                    console.log("Login error:", error.code, error.message);
                    alert("Login error: " + error.message);
                });
        });
    } else {
        console.log("Login button not found");
    }

    // Sign-out event listener
    const signOutButton = document.getElementById("sign-out");
    if (signOutButton) {
        signOutButton.addEventListener('click', function () {
            console.log("Attempting to sign out");
            signOut(auth)
                .then(() => {
                    console.log("Sign out successful");
                    document.cookie = "token=;path=/;SameSite=Strict";
                    window.location = "/";
                })
                .catch((error) => {
                    console.log("Sign out error:", error);
                });
        });
    }
});

// Update UI based on authentication state
function updateUI(cookie) {
    var token = parseCookieToken(cookie);
    if (token.length > 0) {
        const loginBox = document.getElementById("login-box");
        const signOutButton = document.getElementById("sign-out");
        
        if (loginBox) loginBox.hidden = true;
        if (signOutButton) signOutButton.hidden = false;
    } else {
        const loginBox = document.getElementById("login-box");
        const signOutButton = document.getElementById("sign-out");
        
        if (loginBox) loginBox.hidden = false;
        if (signOutButton) signOutButton.hidden = true;
    }
}

// Parse authentication token from cookie
function parseCookieToken(cookie) {
    var strings = cookie.split(';');
    for (let i = 0; i < strings.length; i++) {
        var temp = strings[i].trim().split('=');
        if (temp[0] === "token") {
            return temp[1];
        }
    }
    return "";

}
