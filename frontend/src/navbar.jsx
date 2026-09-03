

import { Link } from "react-router-dom";
// import "bootstrap/dist/css/bootstrap.min.css";

function Navbar() {
  return (
    <nav className="navbar navbar-expand-lg navbar-dark bg-dark">
      <div className="container-fluid">
        
        {/* Brand */}
        <Link className="navbar-brand" to="/">
          Movie Reviews
        </Link>

        <button
          className="navbar-toggler"
          type="button"
          data-bs-toggle="collapse"
          data-bs-target="#navbarNav"
        >
          <span className="navbar-toggler-icon"></span>
        </button>

        <div className="collapse navbar-collapse" id="navbarNav">

          {/* Left side */}
          <ul className="navbar-nav me-auto">
            <li className="nav-item">
              <Link className="nav-link" to="/all-movies">All Movies</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/my-reviews">My Reviews</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/shared-with-me">Shared With Me</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/all-reviews">All Reviews</Link>
            </li>
          </ul>

          {/* Right side */}
          <ul className="navbar-nav ms-auto">
            <li className="nav-item">
              <Link className="nav-link" to="/edit-profile">Edit Profile</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/change-password">Change Password</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link text-warning" to="/logout">Logout</Link>
            </li>
          </ul>

        </div>
      </div>
    </nav>
  );
}

export default Navbar;
