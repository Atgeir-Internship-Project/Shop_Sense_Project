import React from 'react'

function EditProfile() {
    return (
          <div className="container-fluid  text-white py-5 min-vh-100 d-flex justify-content-center align-items-center">
            <div className="card p-5 shadow-lg" style={{ maxWidth: '500px', width: '100%' }}>
                <h2 className="text-center mb-4 text-dark">Edit Profile </h2>

                <div className="mb-3">
                    <label className="form-label text-dark">First Name</label>
                    <input type="text" className="form-control" placeholder="Enter your first name" />
                </div>

                <div className="mb-3">
                    <label className="form-label text-dark">Last Name</label>
                    <input type="text" className="form-control" placeholder="Enter your last name" />
                </div>

                <div className="mb-3">
                    <label className="form-label text-dark">Email address</label>
                    <input type="email" className="form-control" placeholder="name@example.com" />
                </div>

                <div className="mb-3">
                    <label className="form-label text-dark">Mobile Number</label>
                    <input type="tel" className="form-control" placeholder="Enter your phone number" />
                </div>

                <div className="mb-3">
                    <label className="form-label text-dark">Date of Birth</label>
                    <input type="date" className="form-control" placeholder="Enter your birth date" />
                </div>
                
                <button className="btn btn-primary w-100">Register</button>
            </div>
        </div>
    )
}

export default EditProfile
