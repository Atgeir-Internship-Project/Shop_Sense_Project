// import { useState } from 'react'
// import { BrowserRouter, Routes, Route } from "react-router-dom";

// import './App.css'

// import AllMovies from './pages/AllMovies';
// import MyReviews from './pages/MyReviews';
// import SharedWithMe from './pages/SharedWithMe';
// import AllReviews from './AllReviews';
// import EditProfile from './pages/EditProfile';
// import ChangePassword from './pages/ChangePassword';
// import Navbar from './navbar'
// import Home from './pages/Home';
// import Login from './pages/login';
// import Register from './pages/Register';
// import Logout from './pages/Logout';

// function App() {
//   const [count, setCount] = useState(0)

//    return (
//     <BrowserRouter>
//       <Navbar />

       

//       <Routes>

// <Route path="/login" element={<Login />} />
//         <Route path="/register" element={<Register />} />

//         <Route path="/" element={<Home />} />
//         <Route path="/all-movies" element={<AllMovies />} />
//         <Route path="/my-reviews" element={<MyReviews />} />
//         <Route path="/shared-with-me" element={<SharedWithMe />} />
//         <Route path="/all-reviews" element={<AllReviews />} />
//         <Route path="/edit-profile" element={<EditProfile />} />
//         <Route path="/change-password" element={<ChangePassword />} />
//         <Route path="/logout" element={<Logout />} />
//       </Routes>
//     </BrowserRouter>
//   );
// }

// export default App


import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";

import './App.css'

import AllMovies from './pages/AllMovies';
import MyReviews from './pages/MyReviews';
import SharedWithMe from './pages/SharedWithMe';
import AllReviews from './AllReviews';
import EditProfile from './pages/EditProfile';
import ChangePassword from './pages/ChangePassword';
import Navbar from './navbar';
import Home from './pages/Home';
import Login from './pages/login';
import Register from './pages/Register';
import Logout from './pages/Logout';

function AppContent() {
  const location = useLocation();

  // Paths where navbar should NOT show
  const hideNavbarPaths = ['/login', '/register'];

  return (
    <>
      {!hideNavbarPaths.includes(location.pathname) && <Navbar />}

      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/" element={<Home />} />
        <Route path="/all-movies" element={<AllMovies />} />
        <Route path="/my-reviews" element={<MyReviews />} />
        <Route path="/shared-with-me" element={<SharedWithMe />} />
        <Route path="/all-reviews" element={<AllReviews />} />
        <Route path="/edit-profile" element={<EditProfile />} />
        <Route path="/change-password" element={<ChangePassword />} />
        <Route path="/logout" element={<Logout />} />
      </Routes>
    </>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
