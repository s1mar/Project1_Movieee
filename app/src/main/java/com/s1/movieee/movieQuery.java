package com.s1.movieee;

import android.text.format.Time;
import android.util.Log;

import java.net.URL;

/**
 * Created by s1mar_000 on 27-01-2016.
 */
public class movieQuery {

    // member variables

    protected String MovieQuery = "";
    protected URL urlMovieQuery = null;

    public movieQuery() {
        movieQueryGenerator("default");

    }

    protected String year() {
       Time now =new Time();
        now.setToNow();
        String date = now.toString();
        Log.v("Year",date.substring(0,4));
        return date.substring(0,4);



    }


    protected URL movieQueryGenerator(String cat) {


        final String API_KEY = "ENTER YOUR KEY";
        String optionAppend = "/discover/movie?sort_by=popularity.desc";
        //final String BASE_STRING = "http://api.themoviedb.org/3/discover/movie?sort_by=popularity.desc&api_key=[" + API_KEY + "]";
        final String BASE_STRING = "http://api.themoviedb.org/3";

        try {

            switch (cat) {

                case "popular":
                    optionAppend = "/discover/movie?sort_by=popularity.desc";     /*Most popular movies*/
                    break;
                case "ratedR":
                    optionAppend = "/discover/movie/?certification_country=US&certification=R&sort_by=vote_average.desc"; //Best R Rated Movies
                    break;
                case "kidsPopular":
                    optionAppend = "/discover/movie?certification_country=US&certification.lte=G&sort_by=popularity.desc"; //Popular Kids Movies
                    break;
                case "releaseOfTheYear":
                    optionAppend = "/discover/movie?primary_release_year=" + year() + "&sort_by=vote_average.desc"; // Release(s) of the year
                    break;
                default:
                    optionAppend = "/discover/movie?sort_by=popularity.desc";//Most Popular Movies
                    break;

            }

            //Uri movieQuery = Uri.parse(BASE_STRING).buildUpon().appendPath(optionAppend).appendQueryParameter("api_key",API_KEY).build();

            MovieQuery = (BASE_STRING + optionAppend + "&api_key="+API_KEY); // returning the final string
            Log.v("MovieQuery", MovieQuery);
            urlMovieQuery = new URL(MovieQuery);
            return urlMovieQuery;
        } catch (Exception e) {

            Log.e("MovieQuery", e.toString());
        } finally {

            return urlMovieQuery;
        }


    }


}


