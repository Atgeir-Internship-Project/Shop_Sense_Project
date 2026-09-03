// import React from 'react'


// function Register() {
//     return (
//   <div className="container-fluid  text-white py-5 min-vh-100 d-flex justify-content-center align-items-center">
//             <div className="card p-5 shadow-lg" style={{ maxWidth: '500px', width: '100%' }}>
//                 <h2 className="text-center mb-4 text-dark">Sign Up</h2>

//                 <div className="mb-3">
//                     <label className="form-label text-dark">First Name</label>
//                     <input type="text" className="form-control" placeholder="Enter your first name" />
//                 </div>

//                 <div className="mb-3">
//                     <label className="form-label text-dark">Last Name</label>
//                     <input type="text" className="form-control" placeholder="Enter your last name" />
//                 </div>

//                 <div className="mb-3">
//                     <label className="form-label text-dark">Email address</label>
//                     <input type="email" className="form-control" placeholder="name@example.com" />
//                 </div>

//                 <div className="mb-3">
//                     <label className="form-label text-dark">Mobile Number</label>
//                     <input type="tel" className="form-control" placeholder="Enter your phone number" />
//                 </div>

//                 <div className="mb-3">
//                     <label className="form-label text-dark">Date of Birth</label>
//                     <input type="date" className="form-control" placeholder="Enter your birth date" />
//                 </div>

//                 <div className="mb-3">
//                     <label className="form-label text-dark">Password</label>
//                     <input type="password" className="form-control" placeholder="Enter your password" />
//                 </div>

//                 <div className="mb-4"> {/* Increased bottom margin for "Conform Password" */}
//                     <label className="form-label text-dark">Confirm Password</label>
//                     <input type="password" className="form-control" placeholder="Confirm your password" />
//                 </div>

//                 <button className="btn btn-primary w-100">Register</button>
//             </div>
//         </div>
//     )
// }

// export default Register

// src/pages/Register.jsx
import React, { useState } from "react";
import axios from "axios";

function Register() {
  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    email: "",
    mobile: "",
    birth: "",
    password: "",
    confirmpassword: ""
  });

  const [message, setMessage] = useState("");        // success / error message
  const [loading, setLoading] = useState(false);     // disable button while waiting

  const handleChange = (e) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value
    }));
  };

  // submit handler (form submit)
  const handleSubmit = async (e) => {
    e.preventDefault();           // prevent page reload
    setMessage("");

    // basic client-side validation
    if (!formData.email || !formData.password || !formData.confirmpassword) {
      setMessage("Please fill required fields.");
      return;
    }
    if (formData.password !== formData.confirmpassword) {
      setMessage("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      // adjust URL if your backend is hosted elsewhere
      const res = await axios.post("http://localhost:3000/user/signup", formData, {
        // optional: timeout: 5000
      });

      // handle backend response shape
      if (res.data && res.data.status === "success") {
        setMessage("Registration successful!");
        // optionally clear form:
        setFormData({
          first_name: "",
          last_name: "",
          email: "",
          mobile: "",
          birth: "",
          password: "",
          confirmpassword: ""
        });
      } else {
        // backend might return { status: 'error', error: '...' }
        const errText = (res.data && (res.data.error || JSON.stringify(res.data))) || "Unknown server response";
        setMessage(errText);
      }
    } catch (err) {
      console.error("Register error:", err);

      // If server responded with a message:
      if (err.response && err.response.data) {
        // err.response.data expected like { status: 'error', error: '...' }
        setMessage(err.response.data.error || JSON.stringify(err.response.data));
      } else if (err.request) {
        // request made but no response
        setMessage("No response from server. Is the backend running?");
      } else {
        // other error
        setMessage("Request error: " + err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container-fluid text-white py-5 min-vh-100 d-flex justify-content-center align-items-center">
      <div className="card p-5 shadow-lg" style={{ maxWidth: "500px", width: "100%" }}>
        <h2 className="text-center mb-4 text-dark">Sign Up</h2>

        {message && <p className="text-center text-danger">{message}</p>}

        <form onSubmit={handleSubmit}>
          <div className="mb-3">
            <label className="form-label text-dark">First Name</label>
            <input
              type="text"
              name="first_name"
              value={formData.first_name}
              onChange={handleChange}
              className="form-control"
              placeholder="Enter your first name"
            />
          </div>

          <div className="mb-3">
            <label className="form-label text-dark">Last Name</label>
            <input
              type="text"
              name="last_name"
              value={formData.last_name}
              onChange={handleChange}
              className="form-control"
              placeholder="Enter your last name"
            />
          </div>

          <div className="mb-3">
            <label className="form-label text-dark">Email address</label>
            <input
              type="email"
              name="email"
              value={formData.email}
              onChange={handleChange}
              className="form-control"
              placeholder="name@example.com"
              required
            />
          </div>

          <div className="mb-3">
            <label className="form-label text-dark">Mobile Number</label>
            <input
              type="tel"
              name="mobile"
              value={formData.mobile}
              onChange={handleChange}
              className="form-control"
              placeholder="Enter your phone number"
            />
          </div>

          <div className="mb-3">
            <label className="form-label text-dark">Date of Birth</label>
            <input
              type="date"
              name="birth"
              value={formData.birth}
              onChange={handleChange}
              className="form-control"
            />
          </div>

          <div className="mb-3">
            <label className="form-label text-dark">Password</label>
            <input
              type="password"
              name="password"
              value={formData.password}
              onChange={handleChange}
              className="form-control"
              placeholder="Enter your password"
              required
            />
          </div>

          <div className="mb-4">
            <label className="form-label text-dark">Confirm Password</label>
            <input
              type="password"
              name="confirmpassword"
              value={formData.confirmpassword}
              onChange={handleChange}
              className="form-control"
              placeholder="Confirm your password"
              required
            />
          </div>

          <button type="submit" className="btn btn-primary w-100" disabled={loading}>
            {loading ? "Registering..." : "Register"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default Register;
