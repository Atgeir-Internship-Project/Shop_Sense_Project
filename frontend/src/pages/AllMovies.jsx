import React from 'react'

// function AllMovies() {
//     return (
//         <div>
//             <h2>hi</h2>
//         </div>
//     )
// }

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

export default function AllMovies() {
  const [movies, setMovies] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadMovies();
  }, []);

  const loadMovies = async () => {
    try {
      const response = await fetch("/api/movies");
      const data = await response.json();
      setMovies(data);
    } catch (error) {
      console.error("Error loading movies:", error);
    }
    setLoading(false);
  };

  if (loading) return <p>Loading movies...</p>;

  return (
    <div className="all-movies">
      {/* <h1>All Movies</h1>/ */}

      {movies.length === 0 && <p>No movies found.</p>}

      <div className="movie-list">
        {movies.map((movie) => (
          <div key={movie.id} className="movie-card">
            <h3>{movie.title}</h3>
            <p>{movie.description?.slice(0, 100)}...</p>

            <Link to={`/movies/${movie.id}`}>
              <button>View Details</button>
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}



// export default AllMovies
