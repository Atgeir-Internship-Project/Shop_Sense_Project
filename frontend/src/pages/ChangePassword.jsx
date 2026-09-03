import React, { useState } from 'react';


function ChangePassword() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [message, setMessage] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    setMessage('');
    if (newPassword !== confirmNewPassword) {
      setMessage('New password and confirmation do not match.');
      return;
    }
    console.log('Current Password:', currentPassword);
    console.log('New Password:', newPassword);
    setMessage('Password change attempt submitted. (Backend integration needed)');
    setCurrentPassword('');
    setNewPassword('');
    setConfirmNewPassword('');
  };

  return (
    
    <div className="container mt-5">
      <div className="row justify-content-center">
        <div className="col-md-6">
          <div className="card shadow-sm p-4">
            <h2 className="mb-4">Change Password</h2>
            <form onSubmit={handleSubmit}>
             
              <div className="mb-3">
                <label htmlFor="currentPassword" className="form-label">Current Password:</label>
                <input
                  type="password"
                  id="currentPassword"
                  className="form-control"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                />
              </div>
              <div className="mb-3">
                <label htmlFor="newPassword" className="form-label">New Password:</label>
                <input
                  type="password"
                  id="newPassword"
                  className="form-control"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
              </div>
              <div className="mb-3">
                <label htmlFor="confirmNewPassword" className="form-label">Confirm New Password:</label>
                <input
                  type="password"
                  id="confirmNewPassword"
                  className="form-control"
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  required
                />
              </div>
             
              <button type="submit" className="btn btn-primary w-100">
                Change Password
              </button>
            </form>
          
            {message && (
              <div className={`mt-3 alert ${message.includes('match') ? 'alert-danger' : 'alert-info'}`}>
                {message}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ChangePassword;