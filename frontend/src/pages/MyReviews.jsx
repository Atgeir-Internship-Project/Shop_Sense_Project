// import React from 'react'

// // function MyReview() {
// //     

// // }



// import { useEffect, useState } from "react";

//  function MyReviews() {
//   const [reviews, setReviews] = useState([]);
//   const [loading, setLoading] = useState(true);

//   useEffect(() => {
//     loadMyReviews();
//   }, []);

//   const loadMyReviews = async () => {
//     try {
//       const response = await fetch("/api/my-reviews"); // <- your backend route
//       const data = await response.json();
//       setReviews(data);
//     } catch (error) {
//       console.error("Error loading reviews:", error);
//     }
//     setLoading(false);
//   };

//   if (loading) return <p>Loading your reviews...</p>;

//   return (
//     <div className="my-reviews">
//       <h2>My Reviews</h2>

//       {reviews.length === 0 && <p>You have not written any reviews yet.</p>}

//       {reviews.map(review => (
//         <div key={review.id} className="review-card">
//           <h3>{review.movieTitle}</h3>
//           <p><strong>Rating:</strong> {review.rating} / 10</p>
//           <p>{review.text}</p>
//           <hr />
//         </div>
//       ))}
//     </div>
//   );
// }


// export default MyReviews

// import React, { useState, useEffect } from 'react';

// const MyReviews = () => {
//   // Mock reviews data
//   const [reviews, setReviews] = useState([
//     { id: 1, title: "Inception", review: "Amazing movie with mind-bending plot!" },
//     { id: 2, title: "Interstellar", review: "Great visuals and soundtrack!" },
//     { id: 3, title: "The Dark Knight", review: "Best Batman movie ever!" },
//   ]);

//   // Handle delete
//   const handleDelete = (id) => {
//     const confirmDelete = window.confirm("Are you sure you want to delete this review?");
//     if (confirmDelete) {
//       setReviews(reviews.filter((review) => review.id !== id));
//     }
//   };

//   // Handle update
//   const handleUpdate = (id) => {
//     const newReview = prompt("Enter your updated review:");
//     if (newReview) {
//       setReviews(
//         reviews.map((review) =>
//           review.id === id ? { ...review, review: newReview } : review
//         )
//       );
//     }
//   };

//   // Handle share
//   const handleShare = (id) => {
//     const review = reviews.find((r) => r.id === id);
//     alert(`Sharing review: "${review.review}"`);
//     // You can integrate actual sharing logic here
//   };

//   return (
//     <div className="container mt-4">
//       <h2>My Reviews</h2>
//       {reviews.length === 0 ? (
//         <p>You haven't added any reviews yet.</p>
//       ) : (
//         <div className="list-group">
//           {reviews.map((review) => (
//             <div
//               key={review.id}
//               className="list-group-item d-flex justify-content-between align-items-center"
//             >
//               <div>
//                 <h5>{review.title}</h5>
//                 <p>{review.review}</p>
//               </div>
//               <div>
//                 <button
//                   className="btn btn-primary btn-sm me-2"
//                   onClick={() => handleUpdate(review.id)}
//                 >
//                   Update
//                 </button>
//                 <button
//                   className="btn btn-danger btn-sm me-2"
//                   onClick={() => handleDelete(review.id)}
//                 >
//                   Delete
//                 </button>
//                 <button
//                   className="btn btn-success btn-sm"
//                   onClick={() => handleShare(review.id)}
//                 >
//                   Share
//                 </button>
//               </div>
//             </div>
//           ))}
//         </div>
//       )}
//     </div>
//   );
// };

// export default MyReviews;


import React, { useState } from 'react';

const MyReviews = () => {
  const [reviews, setReviews] = useState([
    { id: 1, title: "Inception", review: "Amazing movie with mind-bending plot!" },
    { id: 2, title: "Interstellar", review: "Great visuals and soundtrack!" },
    { id: 3, title: "The Dark Knight", review: "Best Batman movie ever!" },
  ]);

  const [editingId, setEditingId] = useState(null);
  const [updatedReview, setUpdatedReview] = useState('');

  const handleDelete = (id) => {
    const confirmDelete = window.confirm("Are you sure you want to delete this review?");
    if (confirmDelete) {
      setReviews(reviews.filter((review) => review.id !== id));
    }
  };

  const handleEditClick = (id, currentReview) => {
    setEditingId(id);
    setUpdatedReview(currentReview);
  };

  const handleSave = (id) => {
    setReviews(
      reviews.map((review) =>
        review.id === id ? { ...review, review: updatedReview } : review
      )
    );
    setEditingId(null);
    setUpdatedReview('');
  };

  const handleCancel = () => {
    setEditingId(null);
    setUpdatedReview('');
  };

  const handleShare = (id) => {
    const review = reviews.find((r) => r.id === id);
    alert(`Sharing review: "${review.review}"`);
  };

  return (
    <div className="container mt-4">
      <h2>My Reviews</h2>
      {reviews.length === 0 ? (
        <p>You haven't added any reviews yet.</p>
      ) : (
        <div className="list-group">
          {reviews.map((review) => (
            <div
              key={review.id}
              className="list-group-item d-flex justify-content-between align-items-start"
            >
              <div className="flex-grow-1 me-3">
                <h5>{review.title}</h5>
                {editingId === review.id ? (
                  <textarea
                    className="form-control"
                    value={updatedReview}
                    onChange={(e) => setUpdatedReview(e.target.value)}
                  />
                ) : (
                  <p>{review.review}</p>
                )}
              </div>
              <div className="d-flex flex-column">
                {editingId === review.id ? (
                  <>
                    <button
                      className="btn btn-success btn-sm mb-1"
                      onClick={() => handleSave(review.id)}
                    >
                      Save
                    </button>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={handleCancel}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="btn btn-primary btn-sm mb-1"
                      onClick={() => handleEditClick(review.id, review.review)}
                    >
                      Update
                    </button>
                    <button
                      className="btn btn-danger btn-sm mb-1"
                      onClick={() => handleDelete(review.id)}
                    >
                      Delete
                    </button>
                    <button
                      className="btn btn-success btn-sm"
                      onClick={() => handleShare(review.id)}
                    >
                      Share
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MyReviews;

