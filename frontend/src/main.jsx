import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

// Mount the React tree into the <div id="root"> from index.html.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
