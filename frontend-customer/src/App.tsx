import React from "react";
import { Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import Login from "./pages/Login";
import Shop from "./pages/Shop";
import Orders from "./pages/Orders";
import Refunds from "./pages/Refunds";
import Assistant from "./pages/Assistant";
import NotFound from "./pages/NotFound";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Layout />}>
        <Route index element={<Shop />} />
        <Route path="shop" element={<Shop />} />
        <Route path="orders" element={<Orders />} />
        <Route path="refunds" element={<Refunds />} />
        <Route path="assistant" element={<Assistant />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default App;