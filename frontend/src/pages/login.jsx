import React from 'react';

function Login() {
    return (



        
<div>
    <div class="container d-flex justify-content-center align-items-center vh-100">
    <div class="card p-4 shadow-lg form-card">
        <h2 class="text-center mb-4">Sign In</h2>

        <div class="mb-3">
            <label class="form-label">Email address</label>
            <input type="email" class="form-control" placeholder="name@example.com"/>
        </div>

        <div class="mb-3">
            <label class="form-label">Password</label>
            <input type="password" class="form-control" placeholder="Enter your password"/>
        </div>

        <button class="btn btn-primary w-100">Login</button>
    </div>
</div>
</div>
    );
}

export default Login;