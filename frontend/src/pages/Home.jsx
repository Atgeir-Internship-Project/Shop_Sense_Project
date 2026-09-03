import React from 'react'

function Home() {
    return (
        <div>
            
                   <div className="container pt-5">
                        <h2>Create Your Review </h2>
                        <div class="mb-3">
           <label for="exampleFormControlInput1" class="form-label">Rating (1-10) </label>
              <input type="email" class="form-control" id="exampleFormControlInput1" placeholder="Please rate us here "/>
             </div>
             <div class="mb-3">
               <label for="exampleFormControlTextarea1" class="form-label">Your Review here </label>
               <textarea placeholder="your feedback matters please say something about it " class="form-control" id="exampleFormControlTextarea1" rows="3"></textarea>
             </div>
            
              <button className="btn btn-primary w-10">Submit Review </button>
                     </div>
                
            
        </div>
    )
}

export default Home
